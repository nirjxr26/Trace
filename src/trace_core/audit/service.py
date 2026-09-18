"""Audit service: query + verify + export + central record()."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trace_core.audit.domain import AUDIT_LEDGER_NOT_INITIALIZED_MESSAGE, AuditAction
from trace_core.audit.dto import AuditEventDto, AuditFilterDto, VerifyResultDto
from trace_core.audit.events import Context, Subject
from trace_core.audit.models import AuditEventModel
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.service import BaseService

NO_SUCH_TABLE_MESSAGE = "no such table"


def _is_ledger_missing(e: Exception) -> bool:
    orig = getattr(e, "orig", None)
    if getattr(orig, "pgcode", None) == "42P01":
        return True
    msg = str(e).lower()
    if "audit_events" in msg or "audit_chain_state" in msg or NO_SUCH_TABLE_MESSAGE in msg or "no such column" in msg:
        return True
    try:
        arg0 = getattr(orig, "args", [None])[0] if orig is not None else None
        if isinstance(arg0, str) and (NO_SUCH_TABLE_MESSAGE in arg0.lower() or "no such column" in arg0.lower()):
            return True
    except Exception:
        pass
    return False


def _check_ledger_error(e: Exception) -> None:
    from sqlalchemy.exc import DBAPIError

    from trace_core.core.errors import ApplicationError

    # DBAPIError covers OperationalError (SQLite) and ProgrammingError (fresh PG raises
    # UndefinedTable, not OperationalError) — both must map to the migrate guidance.
    if isinstance(e, DBAPIError) and _is_ledger_missing(e):
        raise ApplicationError(AUDIT_LEDGER_NOT_INITIALIZED_MESSAGE) from e
    raise e


@contextmanager
def _ledger_session(manager: DatabaseSessionManager) -> Generator[Session, None, None]:
    """Session boundary mapping missing-ledger DB errors to migrate guidance. Single source."""
    from sqlalchemy.exc import DBAPIError

    try:
        with manager.session() as session:
            yield session
    except DBAPIError as e:
        _check_ledger_error(e)
        raise


class AuditService(BaseService):
    def __init__(self, session_manager: DatabaseSessionManager | None = None):
        super().__init__(session_manager)

    # Central append — application code should call this, not hashing.
    # Runs inside the caller's transaction (via UnitOfWork.before_commit), so a
    # failed append rolls back the case mutation with it: no silent unwitnessed writes.
    def record(
        self,
        session: Session,
        action: AuditAction,
        subject: Subject,
        actor: str,
        details: dict[str, Any] | None = None,
        ctx: Context | None = None,
    ) -> AuditEventDto:
        from trace_core.audit.builder import _ctx as builder_ctx
        from trace_core.audit.builder import merge_details_context
        from trace_core.audit.repository import SqlAlchemyAuditRepository
        from trace_core.core.errors import ValidationError

        if len(actor) > 255:
            raise ValidationError("Actor identifier exceeds maximum length of 255 characters.")
        ctx_obj = ctx
        if ctx_obj is None:
            ctx_obj = builder_ctx(None)
            if not ctx_obj.command:
                ctx_obj = Context(
                    host=ctx_obj.host,
                    trace_version=ctx_obj.trace_version,
                    command=f"{action.value} {subject.number}",
                    os_user=ctx_obj.os_user,
                    session_id=ctx_obj.session_id,
                )
        merged = merge_details_context(details or {}, ctx_obj)
        return SqlAlchemyAuditRepository(session).append(action, actor, subject.number, subject.id, merged)

    def get_by_seq(self, seq: int):  # type: ignore[no-untyped-def]
        if seq < 1:
            from trace_core.core.errors import ValidationError

            raise ValidationError("seq must be >= 1")
        with _ledger_session(self.session_manager) as session:
            from trace_core.audit.repository import get_by_seq

            return get_by_seq(session, seq)

    def head(self) -> tuple[int, str]:
        """Ledger tip without hydrating events. Single source for anchors + tail checks."""
        from trace_core.audit.repository import SqlAlchemyAuditRepository

        with _ledger_session(self.session_manager) as session:
            return SqlAlchemyAuditRepository(session).head()

    def list_events(self, f: AuditFilterDto | None = None):  # type: ignore[no-untyped-def]
        from trace_core.audit.repository import SqlAlchemyAuditRepository

        filt = f or AuditFilterDto()
        with _ledger_session(self.session_manager) as session:
            repo = SqlAlchemyAuditRepository(session)
            return repo.list_events(filt)

    def verify(self) -> VerifyResultDto:
        with _ledger_session(self.session_manager) as session:
            stmt = select(AuditEventModel).order_by(AuditEventModel.seq.asc())
            from trace_core.audit.verifier import verify_rows

            return verify_rows(session.scalars(stmt).yield_per(500))

    def export(self, out_path: str | Path) -> Path:
        out = Path(out_path)
        with _ledger_session(self.session_manager) as session:
            from trace_core.audit.exporter import export_bundle

            return export_bundle(session, out)

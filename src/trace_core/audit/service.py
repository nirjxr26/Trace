"""Audit service: query + verify + export + central record()."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trace_core.audit.domain import AUDIT_LEDGER_NOT_INITIALIZED_MESSAGE, AuditAction
from trace_core.audit.dto import AuditEventDto, AuditEventSummaryDto, AuditFilterDto, VerifyResultDto
from trace_core.audit.events import Context, Subject
from trace_core.audit.models import AuditEventModel
from trace_core.core.database.health import is_missing_relation_error
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.service import BaseService


def _check_ledger_error(e: Exception) -> None:
    from sqlalchemy.exc import DBAPIError

    from trace_core.core.errors import ApplicationError

    # DBAPIError covers OperationalError (SQLite) and ProgrammingError (fresh PG raises
    # UndefinedTable, not OperationalError) — both must map to the migrate guidance.
    if isinstance(e, DBAPIError) and is_missing_relation_error(e):
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
                    command=f"{action.value} {subject.number or ''}".rstrip(),
                    os_user=ctx_obj.os_user,
                    session_id=ctx_obj.session_id,
                )
        merged = merge_details_context(details or {}, ctx_obj)
        return SqlAlchemyAuditRepository(session).append(
            action, actor, subject.number, subject.id, merged, subject_type=subject.type
        )

    def record_hook(
        self,
        build: Callable[[], tuple[AuditAction, Subject, dict[str, Any], Context]],
        actor: str,
        claimed: str | None = None,
    ) -> Callable[[Session], Any]:
        from trace_core.core.operators import current_identity

        def _hook(session: Session) -> Any:
            action, subject, details, ctx = build()
            if claimed and claimed.strip():
                actual, _ = current_identity()
                if claimed.strip() != actual:
                    details = {**details, "claimed_actor": claimed.strip()}
            return self.record(session, action, subject, actor, details, ctx)

        return _hook

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

    def count_events(self, f: AuditFilterDto | None = None) -> int:
        from trace_core.audit.repository import SqlAlchemyAuditRepository

        filt = f or AuditFilterDto()
        with _ledger_session(self.session_manager) as session:
            return SqlAlchemyAuditRepository(session).count_events(filt)

    def list_event_summaries(self, f: AuditFilterDto | None = None) -> list[AuditEventSummaryDto]:
        from trace_core.audit.repository import SqlAlchemyAuditRepository

        filt = f or AuditFilterDto()
        with _ledger_session(self.session_manager) as session:
            return SqlAlchemyAuditRepository(session).list_event_summaries(filt)

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

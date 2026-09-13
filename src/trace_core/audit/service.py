"""Audit service: query + verify + export + central record()."""

from pathlib import Path
from typing import Any

from sqlalchemy import select

from trace_core.audit.domain import AUDIT_LEDGER_NOT_INITIALIZED_MESSAGE, AuditAction
from trace_core.audit.dto import AuditFilterDto, VerifyResultDto
from trace_core.audit.events import Subject
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
    from sqlalchemy.exc import OperationalError

    from trace_core.core.errors import ApplicationError

    if isinstance(e, OperationalError) and _is_ledger_missing(e):
        raise ApplicationError(AUDIT_LEDGER_NOT_INITIALIZED_MESSAGE) from e
    raise e


class AuditService(BaseService):
    def __init__(self, session_manager: DatabaseSessionManager | None = None):
        super().__init__(session_manager)

    # central append — application code should call this, not hashing
    def record(
        self,
        session,  # type: ignore[no-untyped-def]
        action: AuditAction,
        subject: Subject,
        actor: str,
        details: dict | None = None,
        ctx: Any | None = None,  # type: ignore[no-untyped-def]
    ):
        from trace_core.audit.builder import merge_details_context
        from trace_core.audit.events import Context
        from trace_core.audit.repository import SqlAlchemyAuditRepository

        # reuse builder's host/version via Context if already provided
        if isinstance(ctx, Context):
            merged = merge_details_context(details or {}, ctx)
            return SqlAlchemyAuditRepository(session).append(action, actor, subject.number, subject.id, merged)
        if isinstance(ctx, str):
            import socket

            from trace_core.core.settings import settings

            try:
                host = socket.gethostname()
            except Exception:
                host = "unknown"
            ctx_obj = Context(host=host, trace_version=settings.version, command=ctx)
            merged = merge_details_context(details or {}, ctx_obj)
            return SqlAlchemyAuditRepository(session).append(action, actor, subject.number, subject.id, merged)
        # no ctx: build via builder helper (single source)
        from trace_core.audit.builder import _ctx as builder_ctx

        ctx_obj2 = builder_ctx(None)
        # override command to action-specific if builder gave empty
        if not ctx_obj2.command:
            ctx_obj2 = Context(
                host=ctx_obj2.host, trace_version=ctx_obj2.trace_version, command=f"{action.value} {subject.number}"
            )
        merged = merge_details_context(details or {}, ctx_obj2)
        return SqlAlchemyAuditRepository(session).append(action, actor, subject.number, subject.id, merged)

    def get_by_seq(self, seq: int):  # type: ignore[no-untyped-def]
        if seq < 1:
            from trace_core.core.errors import ValidationError

            raise ValidationError("seq must be >= 1")
        from sqlalchemy.exc import OperationalError

        try:
            with self.session_manager.session() as session:
                from trace_core.audit.repository import get_by_seq

                return get_by_seq(session, seq)
        except OperationalError as e:
            _check_ledger_error(e)
            raise

    def list_events(self, f: AuditFilterDto | None = None):  # type: ignore[no-untyped-def]
        from sqlalchemy.exc import OperationalError

        from trace_core.audit.repository import SqlAlchemyAuditRepository

        filt = f or AuditFilterDto()
        try:
            with self.session_manager.session() as session:
                repo = SqlAlchemyAuditRepository(session)
                return repo.list_events(filt)
        except OperationalError as e:
            _check_ledger_error(e)
            raise

    def verify(self) -> VerifyResultDto:
        from sqlalchemy.exc import OperationalError

        try:
            with self.session_manager.session() as session:
                stmt = select(AuditEventModel).order_by(AuditEventModel.seq.asc())
                from trace_core.audit.verifier import verify_rows

                return verify_rows(session.scalars(stmt).yield_per(500))
        except OperationalError as e:
            _check_ledger_error(e)
            raise

    def export(self, out_path: str | Path) -> Path:
        from sqlalchemy.exc import OperationalError

        out = Path(out_path)
        try:
            with self.session_manager.session() as session:
                from trace_core.audit.exporter import export_bundle

                return export_bundle(session, out)
        except OperationalError as e:
            _check_ledger_error(e)
            raise

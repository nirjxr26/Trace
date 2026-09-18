"""Audit event builder: turns domain mutations into ledger payloads. No hashing here."""

from typing import Any
from uuid import UUID

from trace_core.audit.domain import AuditAction
from trace_core.audit.events import Context, Subject
from trace_core.core.operators import process_session_id
from trace_core.core.settings import settings

_CASE_PREFIX = "case "
_AUDIT_PREFIX = "audit "


def _get_argv() -> str:
    import sys

    return " ".join(sys.argv[1:]).strip()


def _resolve_command(command: str | None, argv_cmd: str) -> str:
    if not command:
        return argv_cmd if argv_cmd.startswith((_CASE_PREFIX, _AUDIT_PREFIX)) else ""
    if not command.startswith(_CASE_PREFIX) or not argv_cmd or argv_cmd == command:
        return command or ""
    # enrich placeholder with real argv that has flags
    if argv_cmd.startswith(_CASE_PREFIX) and (len(argv_cmd) > len(command) or "--" in argv_cmd or " -" in argv_cmd):
        return argv_cmd
    return command or ""


def _ctx(command: str | None) -> Context:
    from trace_core.core.operators import current_identity

    os_user, host = current_identity()
    argv_cmd = _get_argv()
    resolved = _resolve_command(command, argv_cmd)
    return Context(
        host=host,
        trace_version=settings.version,
        command=resolved,
        os_user=os_user,
        session_id=process_session_id(),
    )


def _subject_case(number: str, sid: UUID | None) -> Subject:
    return Subject(type="case", number=number, id=sid)


def _case_event(
    action: AuditAction, number: str, sid: UUID | None, details: dict[str, Any], command: str
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return (action, _subject_case(number, sid), details, _ctx(command))


def for_case_created(
    number: str,
    sid: UUID,
    title: str,
    lead_examiner: str,
    command: str | None = None,
    number_source: str = "auto",
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return _case_event(
        AuditAction.CASE_CREATED,
        number,
        sid,
        {"title": title, "lead_examiner": lead_examiner, "number_source": number_source},
        command or f"case create {number}",
    )


def _updated_details(changed: list[str], before: dict[str, Any], after: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "changed": changed,
        "before": {k: before[k] for k in changed},
        "after": {k: after[k] for k in changed},
        "reason": reason,
    }


def for_case_updated(
    number: str,
    sid: UUID,
    changed: list[str],
    before: dict[str, Any],
    after: dict[str, Any],
    reason: str = "",
    command: str | None = None,
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return _case_event(
        AuditAction.CASE_UPDATED,
        number,
        sid,
        _updated_details(changed, before, after, reason),
        command or f"case edit {number}",
    )


def for_case_closed(
    number: str, sid: UUID, reason: str, closed_by: str, command: str | None = None
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return _case_event(
        AuditAction.CASE_CLOSED,
        number,
        sid,
        {"reason": reason, "closed_by": closed_by},
        command or f"case close {number}",
    )


def for_case_archived(
    number: str, sid: UUID | None, command: str | None = None
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return _case_event(AuditAction.CASE_ARCHIVED, number, sid, {}, command or f"case delete {number}")


def for_case_restored(
    number: str, sid: UUID, command: str | None = None
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return _case_event(AuditAction.CASE_RESTORED, number, sid, {}, command or f"case restore {number}")


def for_case_purged(
    number: str, sid: UUID | None, command: str | None = None
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return _case_event(AuditAction.CASE_PURGED, number, sid, {}, command or f"case delete {number} --purge")


def merge_details_context(details: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Flatten Subject/Context into ledger details (no DB change). System provenance wins."""
    out = dict(details)
    out["host"] = ctx.host
    out["trace_version"] = ctx.trace_version
    out["command"] = ctx.command
    out["os_user"] = ctx.os_user
    out["session_id"] = ctx.session_id
    return out

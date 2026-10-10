"""Audit event builder: turns domain mutations into ledger payloads. No hashing here."""

import sys
from typing import Any
from uuid import UUID

from trace_core.audit.domain import AuditAction
from trace_core.audit.events import (
    SUBJECT_TYPE_CASE,
    SUBJECT_TYPE_DEVICE,
    SUBJECT_TYPE_SYSTEM,
    Context,
    Subject,
)
from trace_core.core.operators import process_session_id
from trace_core.core.settings import settings

_CASE_PREFIX = "case "
_AUDIT_PREFIX = "audit "


def _get_argv() -> str:
    return " ".join(sys.argv[1:]).strip()


def _resolve_command(command: str | None, argv_cmd: str) -> str:
    if not command:
        return argv_cmd if argv_cmd.startswith((_CASE_PREFIX, _AUDIT_PREFIX)) else ""
    if not command.startswith(_CASE_PREFIX) or not argv_cmd or argv_cmd == command:
        return command or ""
    # enrich placeholder with real argv that has flags
    if argv_cmd.startswith(_CASE_PREFIX) and (
        len(argv_cmd) > len(command) or any(t.startswith("-") for t in argv_cmd.split())
    ):
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
    return Subject(type=SUBJECT_TYPE_CASE, number=number, id=sid)


def _subject_device() -> Subject:
    return Subject(type=SUBJECT_TYPE_DEVICE, number=None, id=None)


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


def _device_event(
    action: AuditAction, details: dict[str, Any], command: str
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return (action, _subject_device(), details, _ctx(command))


def for_device_inspected(
    node: str,
    serial: str,
    model: str,
    capacity_bytes: int,
    interface: str,
    source: str,
    verdict: str | None = None,
    unknown_cause: str | None = None,
    command: str | None = None,
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    """Identity observation. `node` is hardware-supplied, so it lands in details, not as the subject."""
    details: dict[str, Any] = {
        "node": node,
        "serial": serial,
        "model": model,
        "capacity_bytes": capacity_bytes,
        "interface": interface,
        "source": source,
    }
    if verdict is not None:
        details["verdict"] = verdict
    if unknown_cause is not None:
        details["unknown_cause"] = unknown_cause
    return _device_event(AuditAction.DEVICE_INSPECTED, details, command or f"device inspect {node}")


def for_device_gate_checked(
    node: str,
    verdict: str,
    unknown_cause: str | None,
    evidence: dict[str, Any],
    serial: str | None = None,
    command: str | None = None,
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return _device_event(
        AuditAction.DEVICE_GATE_CHECKED,
        {"node": node, "verdict": verdict, "unknown_cause": unknown_cause, "evidence": evidence, "serial": serial},
        command or f"device check {node}",
    )


def for_device_override(
    node: str,
    original_verdict: str,
    original_unknown_cause: str,
    authorized_by: str,
    reason: str,
    command: str | None = None,
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    """Accepting an unverified source. The pre-override verdict is preserved, never the post one [D19]."""
    return _device_event(
        AuditAction.DEVICE_OVERRIDE,
        {
            "node": node,
            "original_verdict": original_verdict,
            "original_unknown_cause": original_unknown_cause,
            "authorized_by": authorized_by,
            "reason": reason,
        },
        command or f"device check {node} --acknowledge-unverified-source",
    )


def _subject_system() -> Subject:
    return Subject(type=SUBJECT_TYPE_SYSTEM, number=None, id=None)


def for_update_policy_override(
    from_version: str,
    to_version: str,
    authorized_by: str,
    gate: str,
    blocked_reason: str,
    reason: str,
    command: str | None = None,
) -> tuple[AuditAction, Subject, dict[str, Any], Context]:
    return (
        AuditAction.UPDATE_POLICY_OVERRIDE,
        _subject_system(),
        {
            "from_version": from_version,
            "to_version": to_version,
            "authorized_by": authorized_by,
            "gate": gate,
            "blocked_reason": blocked_reason,
            "reason": reason,
        },
        _ctx(command or f"update install {from_version}->{to_version} --bypass-minimum"),
    )


def merge_details_context(details: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Flatten Subject/Context into ledger details (no DB change). System provenance wins."""
    out = dict(details)
    out["host"] = ctx.host
    out["trace_version"] = ctx.trace_version
    out["command"] = ctx.command
    out["os_user"] = ctx.os_user
    out["session_id"] = ctx.session_id
    return out

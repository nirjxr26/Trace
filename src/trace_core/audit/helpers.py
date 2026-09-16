"""Shared audit CLI helpers: seq fetch + case header."""

from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService


def parse_action_value(raw: str | None):  # type: ignore[no-untyped-def]
    """Parse action string to AuditAction or None. No side effects; callers own error UI."""
    if not raw:
        return None
    from trace_core.audit.domain import AuditAction

    try:
        return AuditAction(raw.upper())
    except ValueError:
        return None


def do_show_list(svc: AuditService, filt: AuditFilterDto, case_number: str | None, output: str) -> None:
    """List + timeline + render core shared by Typer and shell. Callers own capture/parse UI."""
    from trace_core.audit.renderers import render_events
    from trace_core.core.ui.renderers import console

    events = svc.list_events(filt)
    if render_case_timeline_view(svc, case_number, events, output):
        return
    if not events and case_number and output.lower() != "json":
        console.print(f"[dim]No events for {case_number}. Try --action CASE_CREATED.[/dim]\n")
        return
    render_events(events, output)


def do_verify(svc: AuditService, output: str, anchor: str | None):  # type: ignore[no-untyped-def]
    """Verify + anchor + render core shared by Typer and shell. Returns result; callers own Tamper policy."""
    from trace_core.audit.anchor import verify_against_anchor
    from trace_core.audit.renderers import render_verify

    res = svc.verify()
    verify_against_anchor(svc, res, anchor)
    render_verify(res, output, anchor)
    return res


def do_export(svc: AuditService, out: str):  # type: ignore[no-untyped-def]
    """Export core shared by Typer and shell. Returns path; callers own messaging."""
    return svc.export(out)


def fetch_case_with_history(case_svc, identifier: str, limit: int = 6):  # type: ignore[no-untyped-def]
    """Case + recent audit events shared by Typer show and shell show. Events None on ledger miss."""
    case = case_svc.get_case(identifier)
    try:
        events = AuditService(case_svc.session_manager).list_events(
            AuditFilterDto(case_number=case.number, limit=limit)
        )
    except Exception:
        events = None
    return case, events


def show_seq_view(svc: AuditService, seq: int, output: str) -> bool:  # type: ignore[no-untyped-def]
    from trace_core.audit.renderers import render_event
    from trace_core.core.ui.renderers import render_error_card

    e = svc.get_by_seq(seq)
    if not e:
        render_error_card("Not Found", f"Audit event seq {seq} does not exist.")
        return False
    render_event(e, output)
    return True


def render_case_timeline_view(svc: AuditService, case_number: str | None, events, output: str) -> bool:  # type: ignore[no-untyped-def]
    """Single source for per-case audit header + timeline. Returns True when handled."""
    if not case_number or output.lower() == "json":
        return False
    from trace_core.audit.renderers import render_audit_timeline, render_case_audit_header
    from trace_core.cases.service import CaseService
    from trace_core.core.errors import NotFoundError
    from trace_core.core.ui.renderers import console

    try:
        case = CaseService(svc.session_manager).get_case(case_number)
    except NotFoundError:
        return False
    render_case_audit_header(case.number, case.title, case.status.value, events)
    if not events:
        console.print(f"[dim]No events for {case_number}. Try --action CASE_CREATED.[/dim]\n")
        return True
    render_audit_timeline(events)
    return True

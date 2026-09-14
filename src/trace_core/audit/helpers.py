"""Shared audit CLI helpers: seq fetch + case header."""

from trace_core.audit.service import AuditService


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

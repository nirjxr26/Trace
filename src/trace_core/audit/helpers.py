"""Shared audit CLI helpers: seq fetch + case header."""

from trace_core.audit.service import AuditService
from trace_core.core.ui.renderers import render_json


def show_seq_view(svc: AuditService, seq: int, output: str) -> bool:  # type: ignore[no-untyped-def]
    from trace_core.audit.renderers import render_audit_detail
    from trace_core.core.ui.renderers import render_error_card

    e = svc.get_by_seq(seq)
    if not e:
        render_error_card("Not Found", f"Audit event seq {seq} does not exist.")
        return False
    if output.lower() == "json":
        render_json(e)
    else:
        render_audit_detail(e)
    return True


def maybe_show_case_header(svc: AuditService, case_number: str | None, events):  # type: ignore[no-untyped-def]
    if not case_number or not events:
        return
    try:
        from trace_core.audit.renderers import render_case_audit_header
        from trace_core.cases.service import CaseService

        case = CaseService(svc.session_manager).get_case(case_number)
        render_case_audit_header(case.number, case.title, case.status.value, events)
    except Exception:
        pass

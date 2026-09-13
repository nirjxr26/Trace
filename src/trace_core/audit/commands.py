"""Typer CLI for audit ledger."""

import typer

from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.database.session import DatabaseSessionManager, db_manager
from trace_core.core.errors import AuditTamperError

audit_app = typer.Typer(name="audit", help="Inspect, verify, and export tamper-evident audit ledger.")


def _get_service(mgr: DatabaseSessionManager | None = None) -> AuditService:
    return AuditService(mgr or db_manager)


def _show_seq(svc: AuditService, seq: int, output: str) -> bool:
    if seq is None:  # type: ignore[truthy-bool]
        return False
    if seq < 1:
        from trace_core.core.ui.renderers import render_error_card

        render_error_card("Invalid seq", "seq must be >= 1.")
        raise typer.Exit(1)
    from trace_core.audit.helpers import show_seq_view

    ok = show_seq_view(svc, seq, output)
    if not ok:
        raise typer.Exit(1)
    return True


def _parse_action(action: str | None):  # type: ignore[no-untyped-def]
    if not action:
        return None
    from trace_core.audit.domain import AuditAction

    try:
        return AuditAction(action.upper())
    except ValueError:
        typer.echo(f"Unknown action '{action}'", err=True)
        raise typer.Exit(1)


def _render_case_timeline(svc: AuditService, case_number: str | None, events, output: str) -> bool:  # type: ignore[no-untyped-def]
    if not case_number or output.lower() == "json":
        return False
    try:
        from trace_core.audit.renderers import render_audit_timeline, render_case_audit_header
        from trace_core.cases.service import CaseService

        case = CaseService(svc.session_manager).get_case(case_number)
        render_case_audit_header(case.number, case.title, case.status.value, events)
        if not events:
            from trace_core.core.ui.renderers import console

            console.print(f"[dim]No events for {case_number}. Try --action CASE_CREATED.[/dim]\n")
            return True
        render_audit_timeline(events)
        return True
    except Exception:
        return False


def _show_list(
    svc: AuditService,
    case_number: str | None,
    action: str | None,
    actor: str | None,
    search: str | None,
    limit: int,
    offset: int,
    output: str,
) -> None:
    from trace_core.audit.renderers import render_audit_table
    from trace_core.core.ui.renderers import render_json

    act = _parse_action(action)
    f = AuditFilterDto(
        case_number=case_number,
        action=act,
        actor=actor,
        search=search,
        limit=limit,
        offset=offset,
    )
    events = svc.list_events(f)
    if output.lower() == "json":
        render_json(events)
        return
    if _render_case_timeline(svc, case_number, events, output):
        return
    if not events and case_number:
        from trace_core.core.ui.renderers import console

        console.print(f"[dim]No events for {case_number}. Try --action CASE_CREATED.[/dim]\n")
        return
    render_audit_table(events)


@audit_app.command("show")
def audit_show(
    case_number: str = typer.Option(None, "--case", help="Filter by case number"),
    action: str = typer.Option(None, "--action", help="Filter by action"),
    actor: str = typer.Option(None, "--actor", help="Filter by actor (substring)"),
    search: str = typer.Option(None, "--search", "-q", help="Search actor/action/case"),
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
    limit: int = typer.Option(50, "--limit", help="Max rows (1..500)"),
    offset: int = typer.Option(0, "--offset", help="Offset"),
    seq: int = typer.Option(None, "--seq", help="Show single event by seq (detailed 5W1H)"),
) -> None:
    with capture_cli_errors("Audit Show"):
        svc = _get_service()
        if seq is not None and _show_seq(svc, seq, output):
            return
        _show_list(svc, case_number, action, actor, search, limit, offset, output)


def _check_anchor(svc: AuditService, res, anchor: str | None) -> None:  # type: ignore[no-untyped-def]
    if not anchor:
        return
    import json
    from pathlib import Path

    try:
        data = json.loads(Path(anchor).read_text(encoding="utf-8"))
        exp_seq = data.get("last_seq")
        exp_chain = data.get("last_chain")
        if res.is_valid and res.last_seq != exp_seq:
            from trace_core.core.ui.renderers import console

            console.print(f"[red]Anchor mismatch: DB last_seq {res.last_seq} != anchor {exp_seq}[/red]")
            raise AuditTamperError(f"Anchor tail mismatch at seq {exp_seq}")
        if res.is_valid and exp_chain:
            events = svc.list_events()
            if events and events[0].chain_hash != exp_chain:
                from trace_core.core.ui.renderers import console

                console.print(f"[red]Anchor chain mismatch: {events[0].chain_hash} != {exp_chain}[/red]")
                raise AuditTamperError("Anchor chain mismatch")
    except AuditTamperError:
        raise
    except Exception as e:
        typer.echo(f"Anchor read failed: {e}", err=True)
        raise typer.Exit(1)


@audit_app.command("verify")
def audit_verify(
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
    anchor: str = typer.Option(None, "--anchor", help="Anchor JSON file to verify tail against"),
) -> None:
    from trace_core.audit.renderers import render_verify_result
    from trace_core.core.ui.renderers import render_json

    with capture_cli_errors("Audit Verify"):
        svc = _get_service()
        res = svc.verify()
        _check_anchor(svc, res, anchor)
        if output.lower() == "json":
            render_json(res)
        else:
            render_verify_result(res)
        if not res.is_valid:
            raise AuditTamperError(f"Tamper detected at seq {res.first_mismatch_seq} ({res.mismatch_type})")


@audit_app.command("export")
def audit_export(
    out: str = typer.Option(..., "--out", help="Output JSONL file path"),
    fmt: str = typer.Option("jsonl", "--format", help="jsonl only in V1"),
) -> None:
    with capture_cli_errors("Audit Export"):
        if fmt.lower() != "jsonl":
            typer.echo("Only --format jsonl supported in V1", err=True)
            raise typer.Exit(1)
        svc = _get_service()
        path = svc.export(out)
        typer.echo(f"Exported audit bundle to {path}")

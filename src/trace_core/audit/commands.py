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


def _parse_action(action: str | None):  # type: ignore[no-untyped-def]
    if not action:
        return None
    from trace_core.audit.domain import AuditAction

    try:
        return AuditAction(action.upper())
    except ValueError:
        typer.echo(f"Unknown action '{action}'", err=True)
        raise typer.Exit(1)


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

    act = _parse_action(action)
    f = AuditFilterDto(
        case_number=case_number,
        action=act,
        actor=actor,
        search=search,
        limit=limit,
        offset=offset,
    )
    from trace_core.audit.helpers import render_case_timeline_view
    from trace_core.audit.renderers import render_events

    events = svc.list_events(f)
    if render_case_timeline_view(svc, case_number, events, output):
        return
    if not events and case_number and output.lower() != "json":
        from trace_core.core.ui.renderers import console

        console.print(f"[dim]No events for {case_number}. Try --action CASE_CREATED.[/dim]\n")
        return
    render_events(events, output)


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
        from trace_core.audit.helpers import show_seq_view

        svc = _get_service()
        if seq is not None:
            if not show_seq_view(svc, seq, output):
                raise typer.Exit(1)
            return
        _show_list(svc, case_number, action, actor, search, limit, offset, output)


@audit_app.command("verify")
def audit_verify(
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
    anchor: str = typer.Option(None, "--anchor", help="Anchor JSON file to verify tail against"),
) -> None:
    from trace_core.audit.renderers import render_verify

    with capture_cli_errors("Audit Verify"):
        from trace_core.audit.anchor import verify_against_anchor

        svc = _get_service()
        res = svc.verify()
        verify_against_anchor(svc, res, anchor)
        render_verify(res, output, anchor)
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

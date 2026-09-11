"""Typer commands for Case management."""

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from trace_core.adapters.db.session import db_manager
from trace_core.application.cases import (
    CaseNotFoundError,
    CaseService,
    DuplicateCaseNumberError,
    InvalidCaseStateError,
)
from trace_core.application.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseUpdateDto,
)
from trace_core.cli.error_handler import render_error_card
from trace_core.cli.exit_codes import EXIT_ERROR, EXIT_NOT_FOUND, EXIT_SUCCESS
from trace_core.cli.ui.renderers import render_case_detail, render_case_table, render_json
from trace_core.domain.models.case import CaseStatus

app = typer.Typer(name="case", help="Create, list, show, edit, and close forensic cases.")
console = Console()


def _get_service() -> CaseService:
    # Ensure tables exist
    db_manager.init_schema()
    return CaseService(db_manager)


@app.command("create")
def create_case(
    title: str = typer.Option(None, "--title", "-t", help="Descriptive title of the case"),
    examiner: str = typer.Option(None, "--examiner", "-e", help="Lead investigator/examiner name"),
    number: str = typer.Option(None, "--number", "-n", help="Case number (leave empty to auto-generate)"),
    description: str = typer.Option(None, "--desc", "-d", help="Detailed case description"),
    notes: str = typer.Option(None, "--notes", help="Preliminary investigation notes"),
    tags: str = typer.Option(None, "--tags", help="Comma-separated tags (e.g. 'usb,laptop')"),
) -> None:
    """Create a new forensic case."""
    try:
        # If parameters not provided on CLI, prompt interactively
        if not title:
            title = Prompt.ask("[cyan]Case Title[/cyan]")
        if not examiner:
            examiner = Prompt.ask("[cyan]Lead Examiner[/cyan]")

        tag_list = [t.strip() for t in tags.split(",")] if tags else []

        service = _get_service()
        dto = CaseCreateDto(
            title=title,
            lead_examiner=examiner,
            number=number,
            description=description,
            notes=notes,
            tags=tag_list,
        )
        created = service.create_case(dto)
        console.print(f"[bold green][OK] Case '{created.number}' created successfully![/bold green]")
        render_case_detail(created)
    except DuplicateCaseNumberError as e:
        render_error_card(
            "Duplicate Case Number",
            str(e),
            "Choose a unique case number or let Trace auto-generate it.",
        )
        raise typer.Exit(EXIT_ERROR)
    except Exception as e:
        render_error_card("Case Creation Failed", str(e), "Verify database connectivity or check configuration.")
        raise typer.Exit(EXIT_ERROR)


@app.command("list")
def list_cases(
    status: str = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status: OPEN, UNDER_REVIEW, CLOSED, ARCHIVED, or ALL",
    ),
    search: str = typer.Option(
        None,
        "--search",
        "-q",
        help="Search string across case number, title, examiner, or description",
    ),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    all_cases: bool = typer.Option(False, "--all", "-a", help="Include soft-deleted / archived cases"),
) -> None:
    """List forensic cases matching search and status criteria."""
    try:
        service = _get_service()

        case_status: CaseStatus | None = None
        if status and status.upper() != "ALL":
            try:
                case_status = CaseStatus(status.upper())
            except ValueError:
                render_error_card(
                    "Invalid Status",
                    f"Status '{status}' is not valid. Valid: OPEN, UNDER_REVIEW, CLOSED, ARCHIVED, ALL.",
                )
                raise typer.Exit(EXIT_ERROR)

        filter_dto = CaseFilterDto(
            status=case_status,
            search=search,
            include_deleted=all_cases,
        )

        cases = service.list_cases(filter_dto)

        if output.lower() == "json":
            render_json(cases)
        else:
            render_case_table(cases)
    except Exception as e:
        render_error_card(
            "Query Failed",
            str(e),
            "Check database connection settings in .env or TRACE_DATABASE_URL.",
        )
        raise typer.Exit(EXIT_ERROR)


@app.command("show")
def show_case(
    identifier: str = typer.Argument(..., help="Case number (e.g. '2026-CR-0001') or UUID"),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table or json"),
) -> None:
    """Display comprehensive case details."""
    try:
        service = _get_service()
        case = service.get_case(identifier)

        if output.lower() == "json":
            render_json(case)
        else:
            render_case_detail(case)
    except CaseNotFoundError as e:
        render_error_card("Case Not Found", str(e), "Run 'trace case list' to inspect available cases.")
        raise typer.Exit(EXIT_NOT_FOUND)
    except Exception as e:
        render_error_card("Query Error", str(e))
        raise typer.Exit(EXIT_ERROR)


@app.command("edit")
def edit_case(
    identifier: str = typer.Argument(..., help="Case number or UUID to edit"),
    title: str = typer.Option(None, "--title", "-t", help="New title"),
    examiner: str = typer.Option(None, "--examiner", "-e", help="New lead examiner"),
    description: str = typer.Option(None, "--desc", "-d", help="Updated description"),
    notes: str = typer.Option(None, "--notes", help="Updated investigation notes"),
    tags: str = typer.Option(None, "--tags", help="Comma-separated tags to overwrite"),
) -> None:
    """Update mutable metadata of a case."""
    try:
        if all(v is None for v in (title, examiner, description, notes, tags)):
            console.print("[dim]No update parameters specified. Case was not modified.[/dim]")
            return

        service = _get_service()
        tag_list = [t.strip() for t in tags.split(",")] if tags is not None else None

        dto = CaseUpdateDto(
            title=title,
            lead_examiner=examiner,
            description=description,
            notes=notes,
            tags=tag_list,
        )
        updated = service.update_case(identifier, dto)
        console.print(f"[bold green][OK] Case '{updated.number}' updated successfully![/bold green]")
        render_case_detail(updated)
    except CaseNotFoundError as e:
        render_error_card("Case Not Found", str(e))
        raise typer.Exit(EXIT_NOT_FOUND)
    except InvalidCaseStateError as e:
        render_error_card("Invalid Operation", str(e))
        raise typer.Exit(EXIT_ERROR)
    except Exception as e:
        render_error_card("Update Failed", str(e))
        raise typer.Exit(EXIT_ERROR)


@app.command("close")
def close_case(
    identifier: str = typer.Argument(..., help="Case number or UUID to close"),
    reason: str = typer.Option("", "--reason", "-r", help="Reason for closing the case"),
    force: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Close a forensic case."""
    try:
        if not force:
            confirmed = Confirm.ask(f"Are you sure you want to close case '{identifier}'?")
            if not confirmed:
                console.print("[dim]Operation cancelled.[/dim]")
                raise typer.Exit(EXIT_SUCCESS)

        service = _get_service()
        closed = service.close_case(identifier, reason=reason)
        console.print(f"[bold green][OK] Case '{closed.number}' has been CLOSED.[/bold green]")
        render_case_detail(closed)
    except CaseNotFoundError as e:
        render_error_card("Case Not Found", str(e))
        raise typer.Exit(EXIT_NOT_FOUND)
    except InvalidCaseStateError as e:
        render_error_card("Illegal State Transition", str(e))
        raise typer.Exit(EXIT_ERROR)
    except Exception as e:
        render_error_card("Closure Failed", str(e))
        raise typer.Exit(EXIT_ERROR)


@app.command("delete")
def delete_case(
    identifier: str = typer.Argument(..., help="Case number or UUID to delete"),
    purge: bool = typer.Option(False, "--purge", help="Permanently purge record from database (irreversible)"),
    force: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete or archive a forensic case."""
    try:
        action_name = "PERMANENTLY PURGE" if purge else "archive/soft-delete"
        if not force:
            confirmed = Confirm.ask(f"Are you sure you want to {action_name} case '{identifier}'?")
            if not confirmed:
                console.print("[dim]Operation cancelled.[/dim]")
                raise typer.Exit(EXIT_SUCCESS)

        service = _get_service()
        success = service.delete_case(identifier, purge=purge)
        if success:
            console.print(f"[bold green][OK] Case '{identifier}' has been {action_name}d.[/bold green]")
        else:
            render_error_card("Delete Failed", f"Could not delete case '{identifier}'.")
            raise typer.Exit(EXIT_ERROR)
    except CaseNotFoundError as e:
        render_error_card("Case Not Found", str(e))
        raise typer.Exit(EXIT_NOT_FOUND)
    except InvalidCaseStateError as e:
        render_error_card("Invalid Operation", str(e))
        raise typer.Exit(EXIT_ERROR)
    except Exception as e:
        render_error_card("Delete Failed", str(e))
        raise typer.Exit(EXIT_ERROR)

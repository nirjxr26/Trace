"""Typer CLI commands for Case operations."""

from uuid import UUID

import typer
from rich.prompt import Confirm, Prompt

from trace_core.cases.domain import STATUS_FILTER_KEYWORDS, CaseStatus, is_archived_filter, parse_status_value
from trace_core.cases.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseUpdateDto,
    parse_tags,
)
from trace_core.cases.renderers import render_case, render_case_detail, render_cases
from trace_core.cases.service import CaseService
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from trace_core.core.cli.output import OUTPUT_HELP, SKIP_CONFIRM_HELP, parse_output_format
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import (
    console,
    format_india_datetime,
    render_error_card,
    render_minimalist_table,
    render_output,
    render_success,
)

case_app = typer.Typer(name="case", help="Create, list, show, edit, review, and close forensic cases.")
_VERIFIED_OPERATION_HELP = "Byte-verified imaging operation UUID"


def _get_service(session_manager: DatabaseSessionManager | None = None) -> CaseService:
    """Service factory. BaseService.__init__ already falls back to the global db_manager."""
    return CaseService(session_manager)


def _confirm_or_exit(prompt: str, action: str) -> None:
    if not Confirm.ask(prompt):
        console.print(f"[dim]{action} cancelled.[/dim]")
        raise typer.Exit(EXIT_SUCCESS)


@case_app.command("imaging")
def list_imaging(
    identifier: str = typer.Argument(..., help="Case number or UUID"),
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
) -> None:
    with capture_cli_errors("Imaging Status Failed"):
        from trace_core.imaging.service import ImagingService

        output_format = parse_output_format(["--output", output])
        operations = ImagingService().list_for_case(identifier)
        render_output(
            output_format,
            [operation.model_dump(mode="json") for operation in operations],
            lambda: render_minimalist_table(
                "Latest imaging operations (up to 100)",
                [("Operation", {}), ("State", {}), ("Bytes", {}), ("SHA-256", {}), ("Created", {})],
                [
                    [
                        str(operation.id),
                        operation.state.value,
                        "" if operation.copied_bytes is None else str(operation.copied_bytes),
                        (operation.acquisition_sha256 or "")[:12],
                        format_india_datetime(operation.created_at),
                    ]
                    for operation in operations
                ],
                empty_message="No imaging operations recorded.",
            ),
        )
        if output_format != "json" and any(operation.state.value == "PREPARING" for operation in operations):
            console.print("[dim]PREPARING is a reservation, not a completed image.[/dim]")


@case_app.command("imaging-abandon")
def abandon_imaging(
    operation_id: UUID = typer.Argument(..., help="Unresolved imaging operation UUID"),
    force: bool = typer.Option(False, "--yes", "-y", help=SKIP_CONFIRM_HELP),
) -> None:
    with capture_cli_errors("Imaging Abandon Failed"):
        if not force:
            _confirm_or_exit("Abandon this imaging operation?", "Abandon")
        from trace_core.imaging.service import ImagingService

        ImagingService().abandon(operation_id)
        render_success("Imaging operation abandoned.")


@case_app.command("imaging-reserve")
def reserve_imaging(
    identifier: str = typer.Argument(..., help="Case number or UUID"),
    force: bool = typer.Option(False, "--yes", "-y", help=SKIP_CONFIRM_HELP),
) -> None:
    with capture_cli_errors("Imaging Reservation Failed"):
        if not force:
            _confirm_or_exit("Reserve an imaging operation for this case?", "Reservation")
        from trace_core.imaging.service import ImagingService

        operation = ImagingService().reserve(identifier)
        render_success(f"Imaging reservation {operation.id} created.")
        console.print("[dim]Reservation only; no image acquired. Acquire with `trace case imaging-acquire`.[/dim]")


@case_app.command("imaging-acquire")
def acquire_imaging(
    operation_id: UUID = typer.Argument(..., help="Unresolved imaging reservation UUID"),
    source: str = typer.Option(..., "--source", "-s", help="Fixture file or physical device node to image"),
    fixture_root: str = typer.Option(
        None, "--fixture-root", help="Directory holding the fixture source (default: the source's directory)"
    ),
    physical: bool = typer.Option(
        False, "--physical", help="Acquire a real OS device through the write-protection gate"
    ),
    software_write_block: bool = typer.Option(
        False,
        "--allow-software-write-block",
        help="Use Linux kernel software write blocking; development only, NOT EVIDENTIARY",
    ),
    hardware_write_block: bool = typer.Option(
        False,
        "--hardware-write-block",
        help="Attest that a validated hardware write blocker protects the source",
    ),
    force: bool = typer.Option(False, "--yes", "-y", help=SKIP_CONFIRM_HELP),
) -> None:
    with capture_cli_errors("Imaging Acquisition Failed"):
        if not force:
            _confirm_or_exit(f"Acquire {source}?", "Acquisition")
        import time

        from trace_core.devices.renderers import format_bytes
        from trace_core.imaging.service import ImagingService

        last = [0.0]

        def _progress(done: int, total: int) -> None:
            now = time.monotonic()
            if now - last[0] < 0.25:
                return
            last[0] = now
            console.print(f"  [dim]{format_bytes(done)} / {format_bytes(total)}[/dim]")

        operation = ImagingService().acquire(
            operation_id,
            source,
            fixture_root=fixture_root,
            allow_real_hardware=physical,
            allow_software_write_block=software_write_block,
            attest_hardware_write_block=hardware_write_block,
            progress=_progress,
        )
        render_success(f"Image byte-verified for operation {operation.id}.")
        console.print(f"  SHA-256   {operation.acquisition_sha256}")
        console.print(f"  Bytes     {operation.copied_bytes}")
        console.print(f"  Image     {operation.image_relpath}")
        console.print(f"  Manifest  {operation.manifest_relpath}")


@case_app.command("imaging-verify")
def verify_imaging(
    operation_id: UUID = typer.Argument(..., help=_VERIFIED_OPERATION_HELP),
) -> None:
    with capture_cli_errors("Image Verification Failed"):
        from trace_core.imaging.service import ImagingService

        if ImagingService().verify_image(operation_id):
            render_success(f"Image for operation {operation_id} still matches its SHA-256 manifest.")
        else:
            render_error_card("Verification Failed", "The image no longer matches the recorded SHA-256.")
            raise typer.Exit(EXIT_ERROR)


@case_app.command("imaging-seal")
def seal_imaging(
    operation_id: UUID = typer.Argument(..., help=_VERIFIED_OPERATION_HELP),
) -> None:
    with capture_cli_errors("Image Sealing Failed"):
        from trace_core.audit.helpers import prompt_passphrase
        from trace_core.imaging.service import ImagingService

        encryption = ImagingService().seal_image(operation_id, prompt_passphrase(confirm=True))
        render_success(f"Image sealed for operation {operation_id}.")
        console.print(f"  Algorithm  {encryption.algorithm}")
        console.print(f"  Sealed     {encryption.sealed_relpath}")
        console.print(f"  SHA-256    {encryption.plaintext_sha256}")


@case_app.command("imaging-unseal")
def unseal_imaging(
    operation_id: UUID = typer.Argument(..., help=_VERIFIED_OPERATION_HELP),
    out: str = typer.Option(..., "--out", help="Output path for the decrypted raw image"),
) -> None:
    with capture_cli_errors("Image Unsealing Failed"):
        from trace_core.audit.helpers import prompt_passphrase
        from trace_core.imaging.service import ImagingService

        path = ImagingService().open_sealed_image(operation_id, prompt_passphrase(), out)
        render_success(f"Image unsealed and verified: {path}.")


@case_app.command("create")
def create_case(
    title: str = typer.Option(None, "--title", "-t", help="Descriptive title of the case"),
    examiner: str = typer.Option(None, "--examiner", "-e", help="Lead investigator/examiner name"),
    number: str = typer.Option(
        None, "--number", "-n", help="Case number YYYY-CODE-XXXX (leave empty to auto-generate)"
    ),
    description: str = typer.Option(None, "--desc", "-d", help="Detailed case description"),
    notes: str = typer.Option(None, "--notes", help="Preliminary investigation notes"),
    tags: str = typer.Option(None, "--tags", help="Comma-separated tags (e.g. 'usb,laptop')"),
) -> None:
    """Create a new forensic case."""
    with capture_cli_errors(
        "Case Creation Failed", default_remediation="Choose a unique case number or let Trace auto-generate it."
    ):
        if not title:
            title = Prompt.ask("[cyan]Case Title[/cyan]")
        if not examiner:
            examiner = Prompt.ask("[cyan]Lead Examiner[/cyan]")

        tag_list = parse_tags(tags) or []

        service = _get_service()
        dto = CaseCreateDto(
            title=title,
            lead_examiner=examiner,
            number=number,
            description=description,
            notes=notes,
            tags=tag_list,
        )
        created = service.create_case(dto, actor=examiner)
        render_success(f"Case '{created.number}' created.")
        render_case_detail(created)


@case_app.command("list")
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
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
    all_cases: bool = typer.Option(False, "--all", "-a", help="Include soft-deleted / archived cases"),
    recent: bool = typer.Option(False, "--recent", help="Show 5 most recently updated cases"),
) -> None:
    """List forensic cases matching search and status criteria."""
    with capture_cli_errors(
        "Query Failed", default_remediation="Check database connection settings in .env or TRACE_DATABASE_URL."
    ):
        service = _get_service()

        case_status: CaseStatus | None = parse_status_value(status)
        include_deleted = all_cases or is_archived_filter(status)
        deleted_only = is_archived_filter(status) and not all_cases
        if status and status.upper() not in STATUS_FILTER_KEYWORDS and case_status is None:
            render_error_card(
                "Invalid Status",
                f"Status '{status}' is not valid. Valid: OPEN, UNDER_REVIEW, CLOSED, ARCHIVED, ALL.",
            )
            raise typer.Exit(EXIT_ERROR)

        filter_dto = CaseFilterDto(
            status=case_status,
            search=search,
            include_deleted=include_deleted,
            deleted_only=deleted_only,
        )
        if recent:
            filter_dto = filter_dto.with_recent()

        cases = service.list_cases(filter_dto)
        render_cases(cases, output)


@case_app.command("show")
def show_case(
    identifier: str = typer.Argument(..., help="Case number (e.g. '2026-CR-0001') or UUID"),
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
) -> None:
    """Display comprehensive case details."""
    with capture_cli_errors("Show Case", default_remediation="Run `trace case list` to inspect available cases."):
        from trace_core.audit.helpers import fetch_case_with_history
        from trace_core.devices.helpers import do_case_device_rows

        service = _get_service()
        case, events = fetch_case_with_history(service, identifier)
        render_case(case, output, events, do_case_device_rows(service.session_manager, case.number))


@case_app.command("edit")
def edit_case(
    identifier: str = typer.Argument(..., help="Case number or UUID to edit"),
    title: str = typer.Option(None, "--title", "-t", help="New title"),
    examiner: str = typer.Option(None, "--examiner", "-e", help="New lead examiner"),
    description: str = typer.Option(None, "--desc", "-d", help="Updated description"),
    notes: str = typer.Option(None, "--notes", help="Updated investigation notes"),
    tags: str = typer.Option(None, "--tags", help="Comma-separated tags to overwrite"),
    reason: str = typer.Option("", "--reason", "-r", help="Reason for the edit (why)"),
) -> None:
    """Update mutable metadata of a case."""
    with capture_cli_errors("Case Update Failed", default_remediation="Pass at least one field flag, e.g. --title."):
        if all(v is None for v in (title, examiner, description, notes, tags)):
            console.print("[dim]No field updates specified. Case was not modified.[/dim]")
            return

        service = _get_service()
        tag_list = parse_tags(tags)

        dto = CaseUpdateDto(
            title=title,
            lead_examiner=examiner,
            description=description,
            notes=notes,
            tags=tag_list,
        )
        updated = service.update_case(identifier, dto, reason=reason)
        render_success(f"Case '{updated.number}' updated.")
        render_case_detail(updated)


@case_app.command("review")
def review_case(
    identifier: str = typer.Argument(..., help="Case number or UUID to review"),
    resume: bool = typer.Option(False, "--resume", help="Return an under-review case to active work"),
    reason: str = typer.Option("", "--reason", "-r", help="Reason for the review change (why)"),
) -> None:
    """Move a case under review, or return it to active work with --resume."""
    with capture_cli_errors(
        "Case Review Failed", default_remediation="Review an open case, or pass --resume for an under-review case."
    ):
        service = _get_service()
        updated = service.review_case(identifier, resume=resume, reason=reason)
        if resume:
            render_success(f"Case '{updated.number}' returned to active work.")
        else:
            render_success(f"Case '{updated.number}' moved under review.")
        render_case_detail(updated)


@case_app.command("close")
def close_case(
    identifier: str = typer.Argument(..., help="Case number or UUID to close"),
    reason: str = typer.Option("", "--reason", "-r", help="Reason for closing the case"),
    closed_by: str = typer.Option(
        "", "--closed-by", "-c", help="Examiner closing the case (defaults to lead examiner)"
    ),
    force: bool = typer.Option(False, "--yes", "-y", help=SKIP_CONFIRM_HELP),
) -> None:
    """Close and permanently seal a forensic case (type the number to confirm)."""
    with capture_cli_errors(
        "Case Closure Failed", default_remediation="Type the exact case number to confirm, and pass --reason."
    ):
        if not force:
            from trace_core.core.ui.renderers import confirm_typed_number

            if not confirm_typed_number(identifier, "close"):
                raise typer.Exit(EXIT_SUCCESS)

        from trace_core.audit.anchor import describe_anchor

        service = _get_service()
        closed = service.close_case(identifier, reason=reason, closed_by=closed_by, actor=closed_by)
        render_success(f"Case '{closed.number}' closed permanently.")
        line = describe_anchor(service.session_manager, closed.number)
        if line is not None:
            console.print(f"[dim]{line}[/dim]")
        render_case_detail(closed)


@case_app.command("delete")
def delete_case(
    identifier: str = typer.Argument(..., help="Case number or UUID to delete"),
    purge: bool = typer.Option(
        False,
        "--purge",
        help="Permanently purge record from database (irreversible; a recreated number starts a new timeline)",
    ),
    by: str = typer.Option("", "--by", "-b", help="Operator archiving/purging (defaults to lead examiner)"),
    force: bool = typer.Option(False, "--yes", "-y", help=SKIP_CONFIRM_HELP),
) -> None:
    """Delete or archive a forensic case (archive asks y/N, purge asks you to type the number)."""
    with capture_cli_errors(
        "Case Deletion Failed",
        default_remediation="Archived cases restore with `trace case restore`; purged cases cannot.",
    ):
        if not force:
            if purge:
                from trace_core.core.ui.renderers import confirm_typed_number

                if not confirm_typed_number(identifier, "purge"):
                    raise typer.Exit(EXIT_SUCCESS)
            else:
                _confirm_or_exit(f"Are you sure you want to archive case '{identifier}'?", "Archive")

        service = _get_service()
        success = service.delete_case(identifier, purge=purge, actor=by)
        if success:
            render_success(f"Case '{identifier}' purged permanently." if purge else f"Case '{identifier}' archived.")
        else:
            render_error_card("Delete Failed", f"Could not delete case '{identifier}'.")
            raise typer.Exit(EXIT_ERROR)


@case_app.command("restore")
def restore_case(
    identifier: str = typer.Argument(..., help="Case number or UUID to restore"),
    force: bool = typer.Option(False, "--yes", "-y", help=SKIP_CONFIRM_HELP),
) -> None:
    """Restore an archived case back to active retention."""
    with capture_cli_errors(
        "Case Restore Failed",
        default_remediation="Only archived cases restore; run `trace case list --all` to find them.",
    ):
        if not force:
            _confirm_or_exit(f"Are you sure you want to restore case '{identifier}'?", "Restore")

        service = _get_service()
        restored = service.restore_case(identifier)
        render_success(f"Case '{restored.number}' restored.")
        render_case_detail(restored)

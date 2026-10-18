"""Typer CLI commands for device enumeration, inspection and write-protection checks."""

import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.exit_codes import EXIT_SUCCESS
from trace_core.core.cli.output import OUTPUT_HELP
from trace_core.core.ui.renderers import confirm_typed_number, console, render_success, sanitize_terminal
from trace_core.devices.helpers import (
    OVERRIDE_TOKEN,
    do_check,
    do_history,
    do_inspect,
    do_link,
    do_list,
    do_unlink,
)
from trace_core.devices.renderers import render_devices, render_gate, render_history, render_inspection


def confirm_override() -> bool:
    """The typed confirmation for accepting an UNKNOWN source. One implementation for
    the Typer CLI and the REPL, which must both stop on it.

    The REPL accepted `--ack-unverified` with no prompt at all, so the control existed only
    on one surface: an operator who used the shell could manufacture trust over
    unverified evidence without typing anything.
    """
    return confirm_typed_number(OVERRIDE_TOKEN, "accepting an unverified source")


device_app = typer.Typer(
    name="device",
    help="Enumerate devices, capture identity, and verify write protection before imaging.",
    no_args_is_help=True,
)


@device_app.command("list")
def list_devices(
    kind: str = typer.Option("all", "--kind", "-k", help="Filter by kind: all, file, or os"),
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
) -> None:
    """List devices this adapter can see. Reads no device content."""
    with capture_cli_errors("Device Enumeration Failed"):
        render_devices(do_list(None, kind, audit_recognition=True), output=output)


@device_app.command("inspect")
def inspect_device(
    node: str = typer.Argument(..., help="Device node, name, or short id (pd0) exactly as `device list` shows"),
    allow_real_hardware: bool = typer.Option(
        False,
        "--physical",
        "--allow-real-hardware",
        "--real",
        help="Required before touching a physical device; never implied by the adapter",
    ),
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
) -> None:
    """Capture a device identity and record it in the signed ledger."""
    with capture_cli_errors("Device Inspection Failed"):
        from trace_core.devices.helpers import do_node_case_numbers

        render_inspection(
            do_inspect(None, node, allow_real_hardware=allow_real_hardware),
            output=output,
            case_numbers=do_node_case_numbers(None, node),
        )


@device_app.command("check")
def check_device(
    node: str = typer.Argument(..., help="Device node, name, or short id (pd0) exactly as `device list` shows"),
    allow_real_hardware: bool = typer.Option(
        False,
        "--physical",
        "--allow-real-hardware",
        "--real",
        help="Required before touching a physical device; never implied by the adapter",
    ),
    acknowledge_unverified_source: bool = typer.Option(
        False,
        "--acknowledge-unverified-source",
        "--ack-unverified",
        help="Proceed past UNKNOWN only. A writable source is never overridable",
    ),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    reason: str = typer.Option("", "--reason", help="Why an unverified source is accepted; recorded in the ledger"),
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
) -> None:
    """Verify write protection. Aborts with exit 10 when writable, 9 when unknown."""
    with capture_cli_errors("Write-Protection Check Failed"):
        if acknowledge_unverified_source and not assume_yes:
            if not confirm_override():
                raise typer.Exit(EXIT_SUCCESS)
        check = do_check(
            None,
            node,
            allow_real_hardware=allow_real_hardware,
            acknowledge_unverified_source=acknowledge_unverified_source,
            override_reason=reason,
        )
        render_gate(check, output=output)
        if output.lower() != "json":
            if check.verdict.value == "UNKNOWN":
                console.print(
                    "[yellow]Source is UNKNOWN - protection could not be confirmed. "
                    "Accepted unverified; the override is in the ledger.[/yellow]"
                )
            else:
                render_success(f"Source is {check.verdict.value}.")


@device_app.command("history")
def device_history(
    serial: str = typer.Argument(..., help="Device serial, as `device inspect` reports it"),
    limit: int = typer.Option(10, "--limit", "-n", help="How many observations to show"),
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
) -> None:
    """Every prior observation of one device identity, newest first."""
    with capture_cli_errors("Device History Failed"):
        render_history(do_history(None, serial, limit), output=output)


@device_app.command("export")
def device_export(
    out: str = typer.Option(..., "--out", help="Output JSONL file path"),
    case_number: str = typer.Option("", "--case", metavar="CASE", help="Only this case's linked devices"),
    serial: str = typer.Option("", "--serial", help="Only this device identity"),
) -> None:
    """Write stored device observations to a JSONL file."""
    with capture_cli_errors("Device Export Failed"):
        from trace_core.core.database.session import db_manager
        from trace_core.devices.exporter import export_observations

        with db_manager.session() as session:
            path = export_observations(
                session,
                out,
                case_number=case_number or None,
                serial=serial or None,
            )
        render_success(f"Wrote device observations to {path}.")


@device_app.command("link")
def device_link(
    node: str = typer.Argument(..., help="Device node, exactly as `device list` shows"),
    case_number: str = typer.Option(..., "--case", metavar="CASE", help="Case to file the device under"),
    label: str = typer.Option("", "--label", help="Operator note, e.g. an evidence bag number"),
) -> None:
    """File a device under a case. Opens no device and writes no forensic row."""
    with capture_cli_errors("Device Link Failed"):
        link = do_link(None, node, case_number, label=label or None)
        render_success(f"Filed {sanitize_terminal(link.node)} under {link.case_number}.")


@device_app.command("unlink")
def device_unlink(
    node: str = typer.Argument(..., help="Device node, exactly as `device link` recorded"),
    case_number: str = typer.Option(..., "--case", metavar="CASE", help="Case to remove the device from"),
) -> None:
    """Remove a device from a case. Recorded in the ledger."""
    with capture_cli_errors("Device Unlink Failed"):
        do_unlink(None, node, case_number)
        render_success(f"Removed {sanitize_terminal(node)} from {case_number}.")

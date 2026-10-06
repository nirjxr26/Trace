"""Typer CLI commands for device enumeration, inspection and write-protection checks."""

import typer
from rich.prompt import Confirm

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.exit_codes import EXIT_SUCCESS
from trace_core.core.cli.output import OUTPUT_HELP
from trace_core.core.ui.renderers import console, render_success
from trace_core.devices.helpers import do_check, do_inspect, do_list
from trace_core.devices.renderers import render_devices, render_gate, render_inspection

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
        render_devices(do_list(None, kind), output=output)


@device_app.command("inspect")
def inspect_device(
    node: str = typer.Argument(..., help="Device node, name, or short id (pd0) exactly as `device list` shows"),
    allow_real_hardware: bool = typer.Option(
        False,
        "--allow-real-hardware",
        help="Required before touching a physical device; never implied by the adapter",
    ),
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
) -> None:
    """Capture a device fingerprint and record it in the signed ledger."""
    with capture_cli_errors("Device Inspection Failed"):
        render_inspection(do_inspect(None, node, allow_real_hardware=allow_real_hardware), output=output)


@device_app.command("check")
def check_device(
    node: str = typer.Argument(..., help="Device node, name, or short id (pd0) exactly as `device list` shows"),
    allow_real_hardware: bool = typer.Option(
        False,
        "--allow-real-hardware",
        help="Required before touching a physical device; never implied by the adapter",
    ),
    acknowledge_unverified_source: bool = typer.Option(
        False,
        "--acknowledge-unverified-source",
        help="Proceed past UNKNOWN only. A writable source is never overridable",
    ),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
) -> None:
    """Verify write protection. Aborts with exit 10 when writable, 9 when unknown."""
    with capture_cli_errors("Write-Protection Check Failed"):
        if (
            acknowledge_unverified_source
            and not assume_yes
            and not Confirm.ask("Write protection could not be established. Continue anyway and record the override?")
        ):
            console.print("[dim]Check cancelled.[/dim]")
            raise typer.Exit(EXIT_SUCCESS)
        check = do_check(
            None,
            node,
            allow_real_hardware=allow_real_hardware,
            acknowledge_unverified_source=acknowledge_unverified_source,
        )
        render_gate(check, output=output)
        if output.lower() != "json":
            render_success(f"Source is {check.verdict.value}.")

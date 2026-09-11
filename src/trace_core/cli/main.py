"""Trace CLI main entrypoint."""

import sys

import typer

# Ensure UTF-8 output encoding for cross-platform compatibility (Windows cp1252 / Linux UTF-8)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
from trace_core.cli.commands.case import app as case_app
from trace_core.cli.shell import run_interactive_shell
from trace_core.settings import settings

app = typer.Typer(
    name="trace",
    help="Trace — Forensic Data Acquisition & Case Engine.",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Register command groups
app.add_typer(case_app, name="case")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"Trace v{settings.version}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        help="Display Trace version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """If no subcommand is provided, launch into the interactive forensic console."""
    if ctx.invoked_subcommand is None:
        run_interactive_shell()


if __name__ == "__main__":
    app()

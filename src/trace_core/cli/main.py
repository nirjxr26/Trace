"""Trace CLI main entrypoint."""

import sys

import typer

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

from trace_core.cases.commands import case_app
from trace_core.cli.shell import run_interactive_shell
from trace_core.core.cli.db_commands import db_app
from trace_core.core.settings import settings

app = typer.Typer(
    name="trace",
    help="Trace — Forensic Data Acquisition & Case Engine.",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Register feature subcommands
app.add_typer(case_app, name="case")
app.add_typer(db_app, name="db")


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

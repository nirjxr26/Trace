"""Trace CLI main entrypoint."""

import typer

from trace_core.audit.commands import audit_app
from trace_core.cases.commands import case_app
from trace_core.cli.shell import run_interactive_shell
from trace_core.core.cli.db_commands import db_app
from trace_core.core.settings import settings
from trace_core.core.ui.renderers import configure_utf8_streams

configure_utf8_streams()

app = typer.Typer(
    name="trace",
    help="Trace — Forensic Data Imaging & Retrieval Tool.",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Register feature subcommands
app.add_typer(case_app, name="case")
app.add_typer(audit_app, name="audit")
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

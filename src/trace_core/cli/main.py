"""Trace CLI main entrypoint."""

import typer

from trace_core.cli.shell import run_interactive_shell
from trace_core.core.cli.catalog import feature_apps
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
for _name, _sub in feature_apps():
    app.add_typer(_sub, name=_name)


@app.command("tui")
def launch_tui() -> None:
    """Launch the fullscreen live console."""
    from trace_core.tui.app import run_tui

    run_tui()


@app.command("doctor")
def launch_doctor() -> None:
    """Run preflight diagnostics (runtime, database, migrations, storage)."""
    from trace_core.core.cli.doctor import run_doctor

    run_doctor()


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

"""Built-in uninstaller: `trace uninstall`."""

import shutil
from pathlib import Path

import typer

from trace_core.core.cli.args import interactive_terminal
from trace_core.core.cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from trace_core.core.ui.renderers import CLOSING_INDENT, console, done_line, step_line
from trace_core.updates.stages import StageStatus

_APP = "app"
_INSTALL = "install"
_RELEASES = "releases"
_BACKUPS = "backups"
# app last: if anything above fails, the `trace` command is still there to fix it with.
_ALWAYS = (_RELEASES, _BACKUPS, _INSTALL, _APP)
_PURGE_ONLY = ("storage", "trust")


def _shim_paths() -> list[Path]:
    home = Path.home()
    return [home / ".local" / "bin" / "trace", home / ".local" / "bin" / "trace.cmd"]


def _trace_root() -> Path:
    return Path.home() / ".trace"


def _remove(path: Path) -> bool:
    """Remove a path, returning whether it is gone.

    `ignore_errors` is deliberately not used: it hides a partial delete behind a
    success-looking result, which is how an evidence tree ends up half removed
    with the uninstaller reporting success.
    """
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return not path.exists()


def _step(ok: bool, label: str) -> None:
    console.print(step_line(StageStatus.DONE if ok else StageStatus.FAILED, label))


def run_uninstall(purge_data: bool) -> int:
    console.print("Uninstalling Trace\n")
    failures: list[Path] = []
    for target in _ALWAYS:
        path = _trace_root() / target
        if not path.exists():
            continue
        try:
            done = _remove(path)
        except OSError as exc:
            done = False
            console.print(f"[dim]  {exc}[/dim]")
        _step(done, f"Removed ~/.trace/{target}" if done else f"Couldn't remove ~/.trace/{target}")
        if not done:
            failures.append(path)
    shim_ok = True
    if failures:
        # Leaving the launcher in place is what makes a partial uninstall recoverable:
        # without `trace` on PATH the operator has no way to inspect or retry it.
        _step(False, "Kept the `trace` launcher — finish with `trace uninstall`")
    else:
        for shim in _shim_paths():
            if not shim.exists():
                continue
            try:
                _remove(shim)
            except OSError:
                shim_ok = False
        _step(shim_ok, "Removed the `trace` launcher" if shim_ok else "Couldn't remove the `trace` launcher")
    shim_removed = not failures and shim_ok
    console.print(done_line())
    console.print("")
    if purge_data:
        console.print(
            f"{CLOSING_INDENT}Kept: the PostgreSQL server. Drop the data with: DROP DATABASE trace;",
            style="dim",
        )
    else:
        console.print(
            f"{CLOSING_INDENT}Kept: your cases and evidence (~/.trace/storage), signing keys, and the database.",
            style="dim",
        )
        console.print(f"{CLOSING_INDENT}Run `trace uninstall --purge-data` to remove those too.", style="dim")
    if failures:
        console.print("")
        console.print(f"[yellow]{CLOSING_INDENT}Some files could not be removed:[/yellow]")
        for path in failures:
            console.print(f"{CLOSING_INDENT}  {path}")
        if failures:
            console.print(f"{CLOSING_INDENT}The `trace` command still works, so you can check again.")
        console.print(f"{CLOSING_INDENT}Nothing was lost — only these folders were left behind.")
        console.print("")
        return EXIT_ERROR
    if shim_removed:
        console.print(f"{CLOSING_INDENT}Trace has been removed.")
        console.print("")
    console.print("")
    return EXIT_SUCCESS


def uninstall_cmd(
    purge_data: bool = typer.Option(False, "--purge-data", help="Also remove storage, trust keys, and all data."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Remove Trace. Without --purge-data the app is removed but storage, trust keys and the database are kept."""
    if not interactive_terminal() and not yes:
        raise typer.BadParameter("refusing interactive uninstall without --yes in non-interactive mode")
    if not yes:
        if purge_data:
            console.print("This deletes Trace, its old versions, your database backups,")
            console.print("and your cases, evidence and signing keys. Continue?")
        else:
            console.print("This deletes Trace, its old versions, and your database backups.")
            console.print("Your cases, evidence and signing keys are kept. Continue?")
        if not typer.confirm("", default=False):
            raise typer.Exit(EXIT_SUCCESS)
    raise typer.Exit(run_uninstall(purge_data))

"""Built-in uninstaller: `trace uninstall`."""

import shutil
import sys
from pathlib import Path

import typer

from trace_core.core.ui.renderers import console
from trace_core.tui.theme import done_line, step_line
from trace_core.updates.stages import StageStatus

_ALWAYS = ("app", "install")
_PURGE_ONLY = ("storage", "trust")


def _shim_paths() -> list[Path]:
    home = Path.home()
    return [home / ".local" / "bin" / "trace", home / ".local" / "bin" / "trace.cmd"]


def _trace_root() -> Path:
    return Path.home() / ".trace"


def _remove(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        return not path.exists()
    except OSError:
        return False


def _step(ok: bool, label: str) -> None:
    console.print(step_line(StageStatus.DONE if ok else StageStatus.FAILED, label))


def run_uninstall(purge_data: bool) -> int:
    console.print("Uninstalling Trace\n")
    removed_any = False
    for shim in _shim_paths():
        if _remove(shim):
            _step(True, f"Removed launcher {shim.name}")
            removed_any = True
    targets = list(_ALWAYS) + (list(_PURGE_ONLY) if purge_data else [])
    for target in targets:
        if _remove(_trace_root() / target):
            _step(True, f"Removed ~/.trace/{target}")
            removed_any = True
    if not removed_any:
        _step(False, "Nothing found to remove.")
    console.print(done_line())
    console.print("")
    if purge_data:
        console.print("Kept: PostgreSQL server. Drop the data manually if needed: DROP DATABASE trace;", style="dim")
    else:
        console.print(
            "Kept: storage (~/.trace/storage), trust keys (~/.trace/trust), PostgreSQL database.", style="dim"
        )
        console.print("Run `trace uninstall --purge-data` to remove those too.", style="dim")
    return 0


def uninstall_cmd(
    purge_data: bool = typer.Option(False, "--purge-data", help="Also remove storage, trust keys, and all data."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Remove Trace. Without --purge-data the app is removed but storage, trust keys and the database are kept."""
    if not sys.stdin.isatty() and not yes:
        raise typer.BadParameter("refusing interactive uninstall without --yes in non-interactive mode")
    if not yes:
        scope = (
            "the app AND all data (storage, trust keys, database)"
            if purge_data
            else "the app only (storage and database are kept)"
        )
        if not typer.confirm(f"This removes {scope}. Continue?", default=False):
            raise typer.Exit(0)
    raise typer.Exit(run_uninstall(purge_data))

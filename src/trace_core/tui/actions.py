"""Shared TUI action helpers: palette routing, guarded mutations, exports."""

from collections.abc import Callable
from typing import Any

PALETTE_ALIASES = {
    "tab-verify": "tab-settings",
    "tab-integrity": "tab-settings",
    "tab-db": "tab-settings",
    "tab-database": "tab-settings",
    "tab-updates": "tab-settings",
    "db-migrate": "database-migrate",
}


def resolve_palette_command(command: str) -> str:
    """Map stale palette ids to current ids. Single source for app._palette_done."""
    return PALETTE_ALIASES.get(command, command)


def run_guarded(view: Any, fn: Callable[[], str | None]) -> None:
    """Epilogue single source: run fn, toast its message, refresh; toast errors, still refresh."""
    try:
        message = fn()
    except Exception as exc:  # boundary: every service failure becomes a toast, never a crash
        view.app.notify(str(exc), severity="error")
    else:
        if message:
            view.app.notify(message)
    refresh = getattr(view, "refresh_data", None)
    if callable(refresh):
        refresh()


def confirm_overwrite(view: Any, path: str | None, on_yes: Callable[[], None]) -> None:
    """Clobber-guard shared by export buttons. Silent on empty, confirms otherwise."""
    if not path:
        return
    from pathlib import Path

    from trace_core.tui.forms import YesNoModal

    if Path(path).exists():
        view.app.push_screen(
            YesNoModal(f"Overwrite existing file {path}?"),
            lambda ok: on_yes() if ok else None,
        )
    else:
        on_yes()

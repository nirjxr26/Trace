"""Shared TUI action helpers: palette routing, export, and mutation epilogues."""

PALETTE_ALIASES = {
    "tab-verify": "tab-integrity",
    "tab-db": "tab-database",
    "db-migrate": "database-migrate",
}


def resolve_palette_command(command: str) -> str:
    """Map stale palette ids to current ids. Single source for app._palette_done."""
    return PALETTE_ALIASES.get(command, command)


def export_bundle(svc, path: str):  # type: ignore[no-untyped-def]
    """Export core shared by Audit and Integrity views. Returns path; callers own notify."""
    return svc.export(path)


def require_selection(item, noun: str = "a case"):  # type: ignore[no-untyped-def]
    """Return item or None. Callers notify 'Select ... first' when None. Single source."""
    return item if item is not None else None


def mutate(view, fn, success_msg: str) -> None:  # type: ignore[no-untyped-def]
    """Run service mutation, notify, refresh. Callers pass zero-arg fn. Same epilogue everywhere."""
    from trace_core.core.errors import ApplicationError

    try:
        fn()
    except ApplicationError as exc:
        view.app.notify(str(exc), severity="error")
        return
    view.app.notify(success_msg)
    refresh = getattr(view, "refresh_data", None)
    if callable(refresh):
        refresh()

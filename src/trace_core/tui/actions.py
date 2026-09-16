"""Shared TUI action helpers: palette routing."""

PALETTE_ALIASES = {
    "tab-verify": "tab-integrity",
    "tab-db": "tab-database",
    "db-migrate": "database-migrate",
}


def resolve_palette_command(command: str) -> str:
    """Map stale palette ids to current ids. Single source for app._palette_done."""
    return PALETTE_ALIASES.get(command, command)

"""Textual theme mapped from the forensic workstation tokens. Single source: core/ui/theme."""

from collections.abc import Sequence

from rich.text import Text
from textual.theme import Theme

from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS

TRACE_THEME = Theme(
    name="trace",
    primary=THEME_HEX["blue"],
    secondary=THEME_HEX["blue_deep"],
    warning=THEME_HEX["amber"],
    error=THEME_HEX["red"],
    success=THEME_HEX["green"],
    accent=THEME_HEX["blue"],
    foreground=THEME_HEX["value"],
    background=THEME_HEX["background"],
    surface=THEME_HEX["surface"],
    panel=THEME_HEX["border_card"],
    dark=True,
    variables={
        "muted": THEME_TOKENS["muted"],
        "tag": THEME_TOKENS["tag"],
        "surface-active": THEME_TOKENS["surface_active"],
        "surface-elevated": THEME_TOKENS["surface_elevated"],
    },
)

STATUS_COLORS = {
    "OPEN": THEME_TOKENS["status_open"],
    "UNDER_REVIEW": THEME_TOKENS["status_review"],
    "CLOSED": THEME_TOKENS["status_closed"],
    "ARCHIVED": THEME_TOKENS["status_archived"],
}
STATUS_FALLBACK = THEME_HEX["value"]


def status_label(status, is_deleted: bool = False) -> str:  # type: ignore[no-untyped-def]
    """Single source for the status label, including the review abbreviation."""
    label = "ARCHIVED" if is_deleted else str(getattr(status, "value", status))
    return "REVIEW" if label == "UNDER_REVIEW" else label


def status_style(status, is_deleted: bool = False) -> str:  # type: ignore[no-untyped-def]
    """Single source for the status colour."""
    key = "ARCHIVED" if is_deleted else str(getattr(status, "value", status))
    return STATUS_COLORS.get(key, STATUS_FALLBACK)


def status_text(status, is_deleted: bool = False):  # type: ignore[no-untyped-def]
    """Single source for TUI status labels. Byte-identical to CasesView._status_text."""
    return Text(status_label(status, is_deleted), style=status_style(status, is_deleted))


def health_dot(ok: bool):  # type: ignore[no-untyped-def]
    """Single source for health pills (db online, verify verdict dots)."""
    return Text("● ", style="#5FD18A" if ok else "#D06A73")


SELECT_PREFIX = "› "

DOT_OK = THEME_HEX["green"]
DOT_BAD = THEME_HEX["red"]
DOT_INFO = THEME_HEX["blue"]


def dot_line(ok: bool, label: str):  # type: ignore[no-untyped-def]
    """Single source for ●/× status lines. Never color-only: glyph differs too."""
    glyph = "● " if ok else "× "
    body = Text()
    body.append(glyph, style=DOT_OK if ok else DOT_BAD)
    body.append(label)
    return body


def update_status_text(kind: str):  # type: ignore[no-untyped-def]
    """Single source for Updates Previous/Current/Status states. No raw unknown."""
    if kind == "available":
        body = Text()
        body.append("↑ ", style=DOT_INFO)
        body.append("Update available")
        return body
    if kind == "failed":
        return dot_line(False, "Check failed")
    return dot_line(True, "Up to date")


def stage_line(status: str, label: str):
    if status == "done":
        return dot_line(True, label)
    if status == "failed":
        return dot_line(False, label)
    body = Text()
    body.append("◌ ", style=DOT_INFO)
    body.append(label)
    return body


def integrity_line(verified: bool):  # type: ignore[no-untyped-def]
    """Single source for Cases/Audit integrity summary. Hashes live in Integrity tab only."""
    return dot_line(verified, "Verified" if verified else "Mismatch")


def append_kv(body: Text, label: str, value: str) -> None:
    """Single source for `Label     value` detail rows shared by Settings sections."""
    body.append(f"{label:<10} ", style="dim")
    body.append(f"{value}\n")


def table_head_text(columns: list[tuple[str, int]]) -> str:
    """Manual header row aligned to fixed DataTable widths. Single source.

    Measured geometry (ruler probe): width = content width, each column adds
    1 cell padding on BOTH sides, so separators are 2 spaces and text starts
    at 1 + cumulative(width + 2). Used because box borders on
    .datatable--header are ignored by Textual (proven by probe).
    """
    return (" " + "  ".join(label.ljust(width) for label, width in columns)).rstrip()


def header_with_count(columns: Sequence[tuple[str, int]], count: int) -> str:
    """Header row plus the `· N` count suffix. Single source for the two views
    that each assembled this separately in on_mount and again on refresh."""
    return f"{table_head_text(list(columns))}  · {count}"

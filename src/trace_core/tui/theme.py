"""Textual theme mapped from the forensic workstation tokens. Single source: core/ui/theme."""

from collections.abc import Sequence

from rich.text import Text
from textual.theme import Theme

from trace_core.core.ui.renderers import get_status_style_and_label
from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
from trace_core.updates.stages import StageStatus

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


def status_label(status, is_deleted: bool = False) -> str:  # type: ignore[no-untyped-def]
    """Single source for the status label, including the review abbreviation."""
    return get_status_style_and_label(status, is_deleted)[0]


def status_style(status, is_deleted: bool = False) -> str:  # type: ignore[no-untyped-def]
    """Single source for the status colour."""
    return get_status_style_and_label(status, is_deleted)[1]


def status_text(status, is_deleted: bool = False):  # type: ignore[no-untyped-def]
    """Single source for TUI status rendering. Delegates to the terminal's resolver."""
    label, style, _border = get_status_style_and_label(status, is_deleted)
    return Text(label, style=style)


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


def stage_line(status: StageStatus, label: str):
    """Single source for install-stage ●/×/◌ lines. Typed on StageStatus."""
    if status == StageStatus.DONE:
        return dot_line(True, label)
    if status == StageStatus.FAILED:
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


def detail_placeholder(has_rows: bool, empty_message: str) -> Text:
    """Detail-pane placeholder shared by Cases/Audit: empty-list message vs select hint."""
    return Text(empty_message if not has_rows else "Select an entry…", style="dim")


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

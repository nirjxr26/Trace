"""Textual theme mapped from the forensic workstation tokens. Single source: core/ui/theme."""

from rich.text import Text
from textual.theme import Theme

from trace_core.core.ui.theme import THEME_TOKENS

TRACE_THEME = Theme(
    name="trace",
    primary="#72B7D3",
    secondary="#5B8DB8",
    warning="#D7B765",
    error="#D06A73",
    success="#63D391",
    accent="#72B7D3",
    foreground="#E3E7EA",
    background="#0C0C0C",
    surface="#0C0C0C",
    panel="#1E2328",
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


def status_text(status, is_deleted: bool = False):  # type: ignore[no-untyped-def]
    """Single source for TUI status labels. Byte-identical to CasesView._status_text."""
    label = "ARCHIVED" if is_deleted else str(getattr(status, "value", status))
    color = STATUS_COLORS.get("ARCHIVED" if is_deleted else label, "#E5EAF0")
    if label == "UNDER_REVIEW":
        label = "REVIEW"
    return Text(label, style=color)


def health_dot(ok: bool):  # type: ignore[no-untyped-def]
    """Single source for health pills (db online, verify verdict dots)."""
    return Text("● ", style="#5FD18A" if ok else "#D06A73")


SELECT_PREFIX = "› "

DOT_OK = "#5FD18A"
DOT_BAD = "#D06A73"
DOT_INFO = "#72B7D3"


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

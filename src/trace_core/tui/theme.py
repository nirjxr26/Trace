"""Textual theme mapped from the forensic workstation tokens. Single source: core/ui/theme."""

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
    from rich.text import Text

    label = "ARCHIVED" if is_deleted else str(getattr(status, "value", status))
    color = STATUS_COLORS.get("ARCHIVED" if is_deleted else label, "#E5EAF0")
    if label == "UNDER_REVIEW":
        label = "REVIEW"
    return Text(label, style=color)


def health_dot(ok: bool):  # type: ignore[no-untyped-def]
    """Single source for health pills (db online, verify verdict dots)."""
    from rich.text import Text

    return Text("● ", style="#5FD18A" if ok else "#D06A73")

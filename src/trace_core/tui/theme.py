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

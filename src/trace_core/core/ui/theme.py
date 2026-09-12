"""Forensic workstation TUI theme tokens."""

from typing import Final

_COLOR_BORDER: Final[str] = "#3A4A5A"
_COLOR_TITLE: Final[str] = "bold #E8EEF5"
_COLOR_ACCENT: Final[str] = "bold #72B7D3"
_COLOR_GREEN: Final[str] = "bold #5FD18A"
_COLOR_AMBER: Final[str] = "bold #D8B56A"
_COLOR_RED: Final[str] = "bold #D06A73"

THEME_TOKENS: Final[dict[str, str]] = {
    "border": _COLOR_BORDER,
    "border_card": "#273442",
    "border_outer": _COLOR_BORDER,
    "border_primary": "#4F7FAF",
    "border_alert": "#A85D66",
    "title": _COLOR_TITLE,
    "title_hero": _COLOR_TITLE,
    "accent": _COLOR_ACCENT,
    "section_title": _COLOR_ACCENT,
    "label": "#AAB7C5",
    "value": "#E5EAF0",
    "muted": "#687786",
    "tag": "#6FA8B8",
    "status_open": _COLOR_GREEN,
    "status_review": _COLOR_AMBER,
    "status_closed": "bold #A88BD6",
    "status_archived": _COLOR_RED,
    "record_active": _COLOR_GREEN,
    "record_deleted": _COLOR_RED,
    "success": _COLOR_GREEN,
    "warning": _COLOR_AMBER,
    "danger": _COLOR_RED,
}

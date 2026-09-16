"""Forensic workstation TUI theme tokens."""

from typing import Final

_BLUE = "bold #72B7D3"
_GREEN = "bold #63D391"

THEME_TOKENS: Final[dict[str, str]] = {
    # ─────────────────────────────────────────────
    # SURFACES
    # ─────────────────────────────────────────────
    "background": "#0C0C0C",
    "surface": "#0C0C0C",
    "surface_elevated": "#111214",
    "surface_active": "#171A1D",
    # ─────────────────────────────────────────────
    # STRUCTURAL BORDERS — neutral, very low (solid approximations for Rich)
    # ─────────────────────────────────────────────
    "border": "#1D1F21",
    "border_card": "#1E2328",
    "border_outer": "#1E2328",
    "border_subtle": "#15191C",
    "border_primary": "#5B8DB8",
    "border_alert": "#C96A72",
    # ─────────────────────────────────────────────
    # TYPOGRAPHY
    # ─────────────────────────────────────────────
    "title": "bold #F2F4F5",
    "title_hero": "bold #F5F7F8",
    "value": "#E3E7EA",
    "label": "#A7B0B8",
    "muted": "#737C84",
    "disabled": "#4E555B",
    # ─────────────────────────────────────────────
    # INFORMATION / INTERACTION — blue reserved
    # ─────────────────────────────────────────────
    "accent": _BLUE,
    "section_title": _BLUE,
    "link": "#72B7D3",
    "focus": "#5B8DB8",
    "selection": "#182B35",
    # ─────────────────────────────────────────────
    # TAGS / METADATA
    # ─────────────────────────────────────────────
    "tag": "#82AEBE",
    "metadata": "#8A949C",
    # ─────────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────────
    "status_open": _GREEN,
    "status_review": "bold #D7B765",
    "status_closed": "bold #A995D6",
    "status_archived": "bold #87939B",
    # ─────────────────────────────────────────────
    # STATUS BORDERS
    # ─────────────────────────────────────────────
    "border_open": "#63D391",
    "border_review": "#D7B765",
    "border_closed": "#A995D6",
    "border_archived": "#87939B",
    # ─────────────────────────────────────────────
    # ACTION SEMANTICS
    # ─────────────────────────────────────────────
    "success": _GREEN,
    "warning": "bold #D7B765",
    "danger": "bold #D06A73",
    "info": _BLUE,
    # ─────────────────────────────────────────────
    # RECORD STATE
    # ─────────────────────────────────────────────
    "record_active": _GREEN,
    "record_deleted": "bold #737C84",
}

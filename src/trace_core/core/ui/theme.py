"""Forensic workstation TUI theme tokens."""

from typing import Final

THEME_HEX: Final[dict[str, str]] = {
    "background": "#0C0C0C",
    "surface": "#0C0C0C",
    "surface_elevated": "#111214",
    "surface_active": "#171A1D",
    "border": "#1D1F21",
    "border_card": "#1E2328",
    "border_subtle": "#15191C",
    "blue": "#72B7D3",
    "blue_deep": "#5B8DB8",
    "green": "#63D391",
    "amber": "#D7B765",
    "violet": "#A995D6",
    "slate": "#87939B",
    "red": "#D06A73",
    "red_border": "#C96A72",
    "title": "#F2F4F5",
    "title_hero": "#F5F7F8",
    "value": "#E3E7EA",
    "label": "#A7B0B8",
    "muted": "#737C84",
    "disabled": "#4E555B",
    "selection": "#182B35",
    "tag": "#82AEBE",
    "metadata": "#8A949C",
}

THEME_TOKENS: Final[dict[str, str]] = {
    # SURFACES
    "background": THEME_HEX["background"],
    "surface": THEME_HEX["surface"],
    "surface_elevated": THEME_HEX["surface_elevated"],
    "surface_active": THEME_HEX["surface_active"],
    # STRUCTURAL BORDERS — neutral, very low (solid approximations for Rich)
    "border": THEME_HEX["border"],
    "border_card": THEME_HEX["border_card"],
    "border_outer": THEME_HEX["border_card"],
    "border_subtle": THEME_HEX["border_subtle"],
    "border_primary": THEME_HEX["blue_deep"],
    "border_alert": THEME_HEX["red_border"],
    # TYPOGRAPHY
    "title": f"bold {THEME_HEX['title']}",
    "title_hero": f"bold {THEME_HEX['title_hero']}",
    "value": THEME_HEX["value"],
    "label": THEME_HEX["label"],
    "muted": THEME_HEX["muted"],
    "disabled": THEME_HEX["disabled"],
    # INFORMATION / INTERACTION — blue reserved
    "accent": f"bold {THEME_HEX['blue']}",
    "section_title": f"bold {THEME_HEX['blue']}",
    "link": THEME_HEX["blue"],
    "focus": THEME_HEX["blue_deep"],
    "selection": THEME_HEX["selection"],
    # TAGS / METADATA
    "tag": THEME_HEX["tag"],
    "metadata": THEME_HEX["metadata"],
    # STATUS
    "status_open": f"bold {THEME_HEX['green']}",
    "status_review": f"bold {THEME_HEX['amber']}",
    "status_closed": f"bold {THEME_HEX['violet']}",
    "status_archived": f"bold {THEME_HEX['slate']}",
    # STATUS BORDERS
    "border_open": THEME_HEX["green"],
    "border_review": THEME_HEX["amber"],
    "border_closed": THEME_HEX["violet"],
    "border_archived": THEME_HEX["slate"],
    # ACTION SEMANTICS
    "success": f"bold {THEME_HEX['green']}",
    "warning": f"bold {THEME_HEX['amber']}",
    "danger": f"bold {THEME_HEX['red']}",
    "info": f"bold {THEME_HEX['blue']}",
    # RECORD STATE
    "record_active": f"bold {THEME_HEX['green']}",
    "record_deleted": f"bold {THEME_HEX['muted']}",
}

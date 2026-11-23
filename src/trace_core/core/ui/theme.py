"""Forensic workstation TUI theme tokens."""

from typing import Final

THEME_HEX: Final[dict[str, str]] = {
    "background": "#0C0C0C",
    "surface": "#0C0C0C",
    "surface_elevated": "#1D1D1F",
    "surface_active": "#29292C",
    "border": "#414145",
    "border_card": "#29292C",
    "border_subtle": "#272729",
    "blue": "#8BC4D9",
    "blue_deep": "#659FB9",
    "green": "#8ACBB2",
    "amber": "#D8C18F",
    "violet": "#B7A5DF",
    "slate": "#B0B3BA",
    "red": "#DC9AA8",
    "red_border": "#B97889",
    "title": "#EEEEF0",
    "title_hero": "#FAFAFB",
    "value": "#E2E2E5",
    "label": "#C5C5CA",
    "muted": "#A3A3AA",
    "disabled": "#77777E",
    "selection": "#35353C",
    "tag": "#B7C4D4",
    "metadata": "#ABABB2",
    "palette_active": "#A9C5DD",
    "scrollbar": "#505055",
    "form_bg": "#141414",
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

"""Forensic workstation TUI theme tokens."""

from typing import Final

THEME_HEX: Final[dict[str, str]] = {
    # Surfaces
    "background": "#0C0C0C",
    "surface": "#0C0C0C",
    "surface_elevated": "#1C1C1E",
    "surface_active": "#252527",
    # Structural borders
    "border": "#303033",
    "border_card": "#262628",
    # Semantic accents
    "blue": "#60A5FA",
    "blue_deep": "#3B82F6",
    "green": "#4ADE80",
    "amber": "#FBBF24",
    "violet": "#A78BFA",
    "slate": "#A1A1AA",
    "red": "#FB7185",
    # Text — two whites plus disabled
    "title": "#EEEEEE",
    "title_hero": "#EEEEEE",
    "value": "#EEEEEE",
    "label": "#C5CDD6",
    "muted": "#C5CDD6",
    "metadata": "#C5CDD6",
    "tag": "#C5CDD6",
    "disabled": "#535D6A",
    # Interaction
    "scrollbar": "#424247",
    "form_bg": "#111111",
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
    "border_primary": THEME_HEX["blue_deep"],
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
    # TAGS / METADATA
    "tag": THEME_HEX["tag"],
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
    # RECORD STATE
    "record_active": f"bold {THEME_HEX['green']}",
}

from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS

SPACE_SM = 1
SPACE_MD = 2
SPACE_LG = 3

LABEL_SM = 10
LABEL_MD = 16
LABEL_LG = 20

PANEL_PADDING = f"{SPACE_SM} {SPACE_MD}"

TITLE_STYLE = THEME_TOKENS["title"]
SECTION_STYLE = THEME_TOKENS["section_title"]

STAGE_TONES = {
    "preflight": THEME_HEX["blue"],
    "acquiring": THEME_HEX["green"],
    "verifying": THEME_HEX["amber"],
    "success": THEME_HEX["green"],
    "sealed": THEME_HEX["violet"],
    "failed": THEME_HEX["red"],
    "cancelled": THEME_HEX["amber"],
    "quarantined": THEME_HEX["red"],
}

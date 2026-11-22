from trace_core.core.ui.theme import THEME_HEX
from trace_core.tui.design.tokens import PANEL_PADDING

MODAL_CSS_PREFIX = (
    f"$muted: {THEME_HEX['muted']};\n$elevated: {THEME_HEX['surface_elevated']};\n$form-bg: {THEME_HEX['form_bg']};\n$active-bg: {THEME_HEX['surface_active']};\n"
)

APP_CSS = """
Screen { background: $background; width: 100%; height: 100%; }
ModalScreen { background: $background 60%; background-tint: transparent; }
TabbedContent { height: 1fr; }
Tabs { height: 1; background: $surface; padding: 0 1; }
Tab { padding: 0 2; color: $muted; height: 1; min-width: 7; background: transparent; }
Tab.-active { color: $text; text-style: bold underline; background: transparent; border: none; }
Tab:hover { color: $text; background: transparent; }
Underline { display: none; }
#hint { height: 1; color: $text; background: $surface; padding: 0 2; }

.pane-host { height: 1fr; }
.pane { border: round $panel; background: $surface; padding: @PANEL_PADDING@; }
.pane-left { width: 1fr; margin-right: 1; }
.pane-right { width: 2fr; scrollbar-size-vertical: 0; scrollbar-size-horizontal: 0; }
.pane-search { border: round $panel; margin-bottom: 1; background: transparent; }
.pane-search:focus { background: transparent; background-tint: transparent; }
.pane-table { height: 1fr; scrollbar-size-vertical: 0; scrollbar-size-horizontal: 0; }
.pane-rule { color: $panel; margin: 0 0 1 0; }
.table-head { text-style: bold; color: $text; height: 1; }

.card-title { color: $accent; text-style: bold; padding: 0; }
#settings-sections { height: 1fr; background: transparent; }
#settings-sections:focus { background-tint: transparent; }
#settings-left .card-subtitle { color: $muted; height: 1; margin-bottom: 1; }
#settings-sections ListItem { height: auto; padding: 0 1; margin-bottom: 0; background: transparent; background-tint: transparent; color: $muted; }
#settings-sections ListItem.-hovered, #settings-sections ListItem.-highlight { background: transparent; background-tint: transparent; border: none; color: $text; text-style: bold; }
#audit-scope { height: 1; color: $muted; }
#device-summary { height: 1; color: $muted; padding-left: 1; margin: 1 0; }
#device-search { margin-bottom: 0; padding: 0 2; }

VerticalScroll { scrollbar-size: 1 1; }
* { scrollbar-background: transparent; scrollbar-color: $scrollbar; scrollbar-corner-color: transparent; }
.muted { color: $muted; }

.modal-box { border: round $panel 50%; background: $surface; padding: 1 2; }
.modal-box-elevated { background: $surface-elevated; }
.modal-input { border: round $panel; height: 1; background: transparent; }
.modal-input:focus { border: round $panel; background: transparent; background-tint: transparent; }
.modal-button { border: none; background: $panel; background-tint: transparent; color: $text; min-width: 16; height: 3; text-align: center; content-align: center middle; margin: 0 2; }
Button.modal-button:hover, Button.modal-button:focus { background: $panel; background-tint: transparent; color: $accent; }
.modal-actions { align: center middle; height: 3; margin-top: 1; }
.modal-field-row { height: 2; align: center middle; }
.modal-field-label { width: 25; color: $text; }
.confirm-prompt { width: 1fr; height: 1; text-align: left; color: $text; text-style: bold; margin-bottom: 0; }
.confirm-input { width: 1fr; height: 1; border: none; background: transparent; padding: 0 1; }
.confirm-button { border: none; background: $panel; background-tint: transparent; color: $text; width: 16; min-width: 16; height: 3; text-align: center; content-align: center middle; margin: 0 1; text-style: bold; }
Button.confirm-button:hover, Button.confirm-button:focus { border: none; background: $panel; background-tint: transparent; color: $accent; text-style: bold; }

DataTable { background: transparent; border: none; }
DataTable > .datatable--header { background: transparent; text-style: bold; }
DataTable > .datatable--cursor { background: $surface-active; color: $text; text-style: bold; }
DataTable > .datatable--hover { background: transparent; }
Input { border: solid $panel; }
Input:focus { border: round $accent; }
Button { margin: 0 1; }
""".replace("@PANEL_PADDING@", PANEL_PADDING)

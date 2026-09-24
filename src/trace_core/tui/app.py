"""Fullscreen Trace console shell: tabs, hint bar, palette, global keys."""

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static, TabbedContent, TabPane

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.theme import TRACE_THEME

TAB_HINTS: dict[str, str] = {
    "cases": "↑↓ Navigate   Enter Open   / Search   r Refresh   q Quit",
    "audit": "↑↓ Navigate   Enter Open   / Search   r Refresh   q Quit",
    "settings": "↑↓ Sections   Enter Run   m Migrate   c Check   q Quit",
}

_TAB_ORDER = ("cases", "audit", "settings")


class TraceApp(App[None]):
    """Live fullscreen console. Views call services; this shell only hosts them."""

    CSS = """
    Screen { background: $background; width: 100%; height: 100%; }
    TabbedContent { height: 1fr; }
    Tabs { height: 1; background: $surface; padding: 0 1; }
    Tab { padding: 0 2; color: $text-muted; height: 1; min-width: 7; background: transparent; }
    Tab.-active { color: #E3E7EA; text-style: bold underline; background: transparent; border: none; }
    Tab:hover { color: $text; background: transparent; }
    Underline { display: none; }
    #hint {
        height: 1;
        color: $muted;
        background: $surface;
        padding: 0 2;
    }
    #cases-top, #audit-main, #settings-top { height: 1fr; }
    #cases-left, #cases-right, #audit-left, #audit-right, #settings-left, #settings-right {
        border: round $panel;
        background: $surface;
        padding: 0 1;
    }
    #cases-right, #audit-right, #settings-right {
        padding: 1 2;
    }
    #cases-left, #audit-left, #settings-left { width: 1fr; margin-right: 1; }
    #cases-right, #audit-right, #settings-right { width: 2fr; }
    #settings-sections { height: 1fr; background: transparent; }
    #settings-sections:focus { background-tint: transparent; }
    #settings-left .card-title { padding: 1 1 1 1; }
    #settings-sections ListItem { height: auto; padding: 0 1; margin-bottom: 1; background: transparent; background-tint: transparent; color: $text-muted; }
    #settings-sections ListItem.-hovered, #settings-sections ListItem.-highlight { background: transparent; background-tint: transparent; border: none; color: $text; text-style: bold; }
    .table-head { text-style: bold; color: $text; height: 1; }
    #settings-left Rule, #cases-left Rule, #audit-left Rule { color: $panel; margin: 0 0 1 0; }
    #case-search, #audit-search { border: round $panel; margin-bottom: 1; background: transparent; }
    #case-search:focus, #audit-search:focus { background: transparent; background-tint: transparent; }
    #audit-scope { height: 1; color: $muted; }
    #integrity-scroll, #database-scroll { height: 1fr; }
    VerticalScroll { scrollbar-size: 1 1; }
    * { scrollbar-background: transparent; scrollbar-color: $panel; scrollbar-corner-color: transparent; }
    .card {
        height: auto;
        border: round $panel;
        background: $surface;
        padding: 1 2;
        margin-bottom: 1;
    }
    .card-title { color: $accent; text-style: bold; }
    .input-row { height: 3; align: center middle; margin-top: 1; }
    .input-row Input { width: 1fr; margin-right: 1; border: round $panel; }
    .input-row Button { min-width: 16; border: round $panel; }
    #db-migrations { height: 1fr; }
    #db-migrations DataTable { height: 1fr; }
    DataTable { background: transparent; border: none; }
    DataTable > .datatable--header { background: transparent; text-style: bold; }
    DataTable > .datatable--cursor { background: $surface-active; color: $text; text-style: bold; }
    DataTable > .datatable--hover { background: $surface-active; }
    Input { border: solid $panel; }
    Input:focus { border: round $accent; }
    Button { margin: 0 1; }
    .panel-title { color: $accent; text-style: bold; }
    .muted { color: $muted; }
    """

    BINDINGS = [
        Binding("1", "tab('cases')", "Cases"),
        Binding("2", "tab('audit')", "Audit"),
        Binding("3", "tab('settings')", "Settings"),
        Binding("left", "prev_tab", "Prev tab", show=False),
        Binding("right", "next_tab", "Next tab", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("ctrl+p", "palette", "Commands"),
        Binding("question_mark", "keys", "Keys"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._session_manager = session_manager
        self.register_theme(TRACE_THEME)
        self.theme = "trace"

    @property
    def session_manager(self) -> DatabaseSessionManager | None:
        """Injected manager (tests) or None for the shared global. Passed to every view."""
        return self._session_manager

    def compose(self) -> ComposeResult:
        from trace_core.tui.screens.audit import AuditView
        from trace_core.tui.screens.cases import CasesView
        from trace_core.tui.screens.settings import SettingsView

        with TabbedContent(initial="cases"):
            with TabPane("Cases", id="cases"):
                yield CasesView(self._session_manager)
            with TabPane("Audit", id="audit"):
                yield AuditView(self._session_manager)
            with TabPane("Settings", id="settings"):
                yield SettingsView(self._session_manager)
        yield Static(TAB_HINTS["cases"], id="hint")

    def on_mount(self) -> None:
        self.query_one("#hint", Static).update(TAB_HINTS["cases"])
        view = self.current_view()
        focus = getattr(view, "focus_default", None)
        if callable(focus):
            focus()

    def action_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_prev_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        current = tabs.active or _TAB_ORDER[0]
        idx = _TAB_ORDER.index(current) if current in _TAB_ORDER else 0
        tabs.active = _TAB_ORDER[(idx - 1) % len(_TAB_ORDER)]

    def action_next_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        current = tabs.active or _TAB_ORDER[0]
        idx = _TAB_ORDER.index(current) if current in _TAB_ORDER else 0
        tabs.active = _TAB_ORDER[(idx + 1) % len(_TAB_ORDER)]

    def action_refresh(self) -> None:
        view = self.current_view()
        refresh = getattr(view, "refresh_data", None)
        if callable(refresh):
            refresh()

    def action_palette(self) -> None:
        from trace_core.tui.palette import PaletteModal

        self.push_screen(PaletteModal(self), self._palette_done)

    def _palette_done(self, command: str | None) -> None:
        if not command:
            return
        from trace_core.tui.actions import resolve_palette_command

        command = resolve_palette_command(command)
        if command.startswith("tab-"):
            self.action_tab(command.removeprefix("tab-"))
            return
        view = self.current_view()
        run = getattr(view, "run_command", None)
        if callable(run):
            run(command)

    def action_keys(self) -> None:
        from trace_core.tui.palette import KeysModal

        self.push_screen(KeysModal())

    @on(TabbedContent.TabActivated)
    def _tab_switched(self, event: TabbedContent.TabActivated) -> None:
        from textual.css.query import NoMatches

        tab = event.pane.id or "cases"
        try:
            self.query_one("#hint", Static).update(TAB_HINTS.get(tab, ""))
        except NoMatches:
            pass  # initial activation fires before the hint bar mounts
        try:
            view = event.pane.query_one("*")
        except NoMatches:
            return  # content mounts lazily; each view refreshes in its own on_mount
        refresh = getattr(view, "refresh_data", None)
        if callable(refresh):
            refresh()
        focus = getattr(view, "focus_default", None)
        if callable(focus):
            focus()

    def current_view(self) -> object | None:
        """Active tab's view widget, if it exposes refresh_data."""
        try:
            pane = self.query_one(TabbedContent).active_pane
            return pane.query_one("*") if pane is not None else None
        except Exception:
            return None


def run_tui(session_manager: DatabaseSessionManager | None = None) -> None:
    """Entrypoint for `trace tui`."""
    TraceApp(session_manager).run()

"""Fullscreen Trace console shell: tabs, hint bar, palette, global keys."""

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.notifications import SeverityLevel
from textual.widgets import Static, TabbedContent, TabPane

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.theme import THEME_HEX
from trace_core.tui.design.css import APP_CSS
from trace_core.tui.theme import TRACE_THEME

TAB_HINTS: dict[str, str] = {
    "cases": "↑↓ Navigate   / Search   Ctrl+P Commands   q Quit",
    "devices": "↑↓ Navigate   / Search   Ctrl+P Commands   q Quit",
    "audit": "↑↓ Navigate   Enter Open   / Search   Ctrl+P Commands   q Quit",
    "settings": "↑↓ Sections   Enter Run   Ctrl+P Commands   q Quit",
    "imaging": "↑↓ Operations   / Search   Ctrl+P Commands   q Quit",
}

_TAB_ORDER = ("cases", "devices", "imaging", "audit", "settings")


def _hint_text(hint: str) -> Text:
    text = Text()
    for index, part in enumerate(hint.split("   ")):
        token = part.strip()
        if not token:
            continue
        if index:
            text.append("   ")
        key, _, label = token.partition(" ")
        text.append(key, style=THEME_HEX["value"])
        if label:
            text.append(f" {label}", style=THEME_HEX["muted"])
    return text


class TraceApp(App[None]):
    """Live fullscreen console. Views call services; this shell only hosts them."""

    ENABLE_COMMAND_PALETTE = False

    CSS = APP_CSS

    BINDINGS = [
        Binding("1", "tab('cases')", "Cases"),
        Binding("2", "tab('devices')", "Devices"),
        Binding("3", "tab('imaging')", "Imaging"),
        Binding("4", "tab('audit')", "Audit"),
        Binding("5", "tab('settings')", "Settings"),
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
        self._last_tab: str | None = None
        self.register_theme(TRACE_THEME)
        self.theme = "trace"

    @property
    def session_manager(self) -> DatabaseSessionManager | None:
        """Injected manager (tests) or None for the shared global. Passed to every view."""
        return self._session_manager

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = False,
    ) -> None:
        super().notify(message, title=title, severity=severity, timeout=timeout, markup=markup)

    def compose(self) -> ComposeResult:
        from trace_core.tui.screens.audit import AuditView
        from trace_core.tui.screens.cases import CasesView
        from trace_core.tui.screens.devices import DevicesView
        from trace_core.tui.screens.imaging import ImagingView
        from trace_core.tui.screens.settings import SettingsView

        with TabbedContent(initial="cases"):
            with TabPane("Cases", id="cases"):
                yield CasesView(self._session_manager)
            with TabPane("Devices", id="devices"):
                yield DevicesView(self._session_manager)
            with TabPane("Imaging", id="imaging"):
                yield ImagingView(self._session_manager)
            with TabPane("Audit", id="audit"):
                yield AuditView(self._session_manager)
            with TabPane("Settings", id="settings"):
                yield SettingsView(self._session_manager)
        yield Static(_hint_text(TAB_HINTS["cases"]), id="hint")

    def on_mount(self) -> None:
        self.query_one("#hint", Static).update(_hint_text(TAB_HINTS["cases"]))
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

        tabs = self.query_one(TabbedContent)
        self.push_screen(PaletteModal(tabs.active or "cases"), self._palette_done)

    def _palette_done(self, command: str | None) -> None:
        if not command:
            return
        from trace_core.tui.actions import resolve_palette_command
        from trace_core.tui.palette import command_scope

        command = resolve_palette_command(command)
        tabs = self.query_one(TabbedContent)
        if command.startswith("tab-"):
            self.action_tab(command.removeprefix("tab-"))
            return
        scope = command_scope(command)
        if scope and scope in _TAB_ORDER and tabs.active != scope:
            tabs.active = scope
            self.call_later(self._run_palette_command, command, scope)
            return
        self._run_palette_command(command, tabs.active or "cases")

    def _run_palette_command(self, command: str, target_tab: str) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active != target_tab:
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
        if tab == self._last_tab:
            return
        self._last_tab = tab
        try:
            self.query_one("#hint", Static).update(_hint_text(TAB_HINTS.get(tab, "")))
        except NoMatches:
            pass  # initial activation fires before the hint bar mounts
        try:
            view = event.pane.query_one("*")
        except NoMatches:
            return  # content mounts lazily; each view refreshes in its own on_mount
        enter = getattr(view, "activate", None)
        if not callable(enter):
            enter = getattr(view, "refresh_data", None)
        if callable(enter):
            enter()
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

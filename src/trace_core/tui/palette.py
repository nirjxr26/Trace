"""Command palette + key map overlay. Fuzzy engine reused from core completion."""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from trace_core.core.cli.completion import filter_completions
from trace_core.tui.forms import _BaseModal

_CONFIRM_HINT = "y/N confirm"
PALETTE_LIST_SELECTOR = "#palette-list"

COMMANDS: list[tuple[str, str, str]] = [
    # (command id, label, hint)
    ("tab-cases", "Cases", "case table + dossier"),
    ("tab-devices", "Devices", "enumeration + gate"),
    ("tab-audit", "Audit", "ledger + verification"),
    ("tab-settings", "Settings", "database + updates"),
    ("tab-imaging", "Imaging", "RAW acquisition"),
    ("case-create", "New case", "guided form"),
    ("case-edit", "Edit case", "diff + reason"),
    ("case-review", "Review case", "to/from under review"),
    ("case-close", "Close case", f"seal; type number, {_CONFIRM_HINT}"),
    ("case-archive", "Archive case", _CONFIRM_HINT),
    ("case-purge", "Purge case", "type number, irreversible"),
    ("case-restore", "Restore case", _CONFIRM_HINT),
    ("case-recent", "Recent cases", "5 most updated"),
    ("audit-export", "Export audit", "header + JSONL"),
    ("audit-anchor", "Check anchor", "tail check"),
    ("device-inspect", "Inspect device", "fingerprint"),
    ("device-check", "Check device", "write-protection gate"),
    ("device-link", "Link device", "file under case"),
    ("device-unlink", "Unlink device", "ledger recorded"),
    ("device-history", "Device history", "newest first"),
    ("device-export", "Export devices", "JSONL"),
    ("imaging-reserve", "Reserve image", "bound to case"),
    ("imaging-acquire", "Acquire image", "fixture or resume"),
    ("imaging-acquire-physical", "Acquire physical", "write-protection gate"),
    ("imaging-verify", "Verify image", "whole + piece hashes"),
    ("imaging-seal", "Seal image", "passphrase"),
    ("imaging-unseal", "Unseal image", "decrypt + verify"),
    ("imaging-change-case", "Choose case", "case picker"),
    ("imaging-progress-preview", "Preview progress", "static layout"),
    ("app-status", "Settings", "db · updates · audit"),
]

COMMAND_META: dict[str, tuple[str, str]] = {
    "tab-cases": ("Navigate", "1"),
    "tab-devices": ("Navigate", "2"),
    "tab-imaging": ("Navigate", "3"),
    "tab-audit": ("Navigate", "4"),
    "tab-settings": ("Navigate", "5"),
    "case-create": ("Cases", "c"),
    "case-edit": ("Cases", "e"),
    "case-review": ("Cases", "w"),
    "case-close": ("Cases", "x"),
    "case-archive": ("Cases", "a"),
    "case-purge": ("Cases", "p"),
    "case-restore": ("Cases", "u"),
    "case-recent": ("Cases", "r"),
    "audit-export": ("Audit", "e"),
    "audit-anchor": ("Audit", "a"),
    "device-inspect": ("Devices", "i"),
    "device-check": ("Devices", "c"),
    "device-link": ("Devices", "l"),
    "device-unlink": ("Devices", "u"),
    "device-history": ("Devices", ""),
    "device-export": ("Devices", ""),
    "imaging-reserve": ("Imaging", "n"),
    "imaging-acquire": ("Imaging", "a"),
    "imaging-acquire-physical": ("Imaging", "p"),
    "imaging-verify": ("Imaging", "v"),
    "imaging-seal": ("Imaging", "s"),
    "imaging-unseal": ("Imaging", "u"),
    "imaging-change-case": ("Imaging", "c"),
    "imaging-progress-preview": ("Imaging", "Ctrl+G"),
    "app-status": ("Settings", "s"),
}

_BY_ID = {command: (label, hint) for command, label, hint in COMMANDS}
_SHORTCUT_OVERRIDES = {"audit-export": "ctrl+x l", "audit-anchor": "ctrl+x n"}


def shortcut_label(command: str) -> str:
    key = COMMAND_META[command][1]
    if command in _SHORTCUT_OVERRIDES:
        return _SHORTCUT_OVERRIDES[command]
    return f"ctrl+x {key}" if len(key) == 1 else key


def command_scope(command: str) -> str | None:
    meta = COMMAND_META.get(command)
    if meta is None or meta[0] == "Navigate":
        return None
    return meta[0].lower()


PALETTE_CSS = """
    PaletteModal { align: center middle; }
    #palette-box { width: 56; height: auto; max-height: 22; border: none; background: $surface-elevated; padding: 2 3; }
    #palette-head { height: 1; margin-bottom: 1; }
    #palette-esc { width: auto; color: $muted; text-align: right; }
    #palette-input { width: 1fr; height: 1; border: none; background: $surface-elevated; padding: 0 0 0 1; }
    #palette-input:focus { border: none; background: $surface-elevated; background-tint: transparent; }
    #palette-list { height: auto; max-height: 12; margin-top: 1; scrollbar-size: 0 0; background: $surface-elevated; }
    #palette-list > ListItem { height: 1; background: transparent; }
    #palette-list > ListItem.group-head { background: transparent; margin-top: 1; }
    #palette-list > ListItem.group-head:first-child { margin-top: 0; }
    #palette-list > ListItem.-highlight,
    #palette-list > ListItem:hover { background: $surface-active; color: $text; border-left: heavy $palette-bar; }
    #palette-list > ListItem.-highlight Static,
    #palette-list > ListItem:hover Static { color: $text; }
    #palette-list > ListItem.-highlight .cmd-key,
    #palette-list > ListItem:hover .cmd-key { color: $muted; }
    .group-label { color: $accent; padding-left: 1; }
    .category-label { color: $text; padding-left: 1; }
    .cmd-columns { height: 1; padding: 0 1; }
    .cmd-label { width: 1fr; }
    .cmd-key { width: auto; min-width: 4; text-align: right; color: $muted; }
    """


class PaletteModal(_BaseModal, ModalScreen[str | None]):
    """Fuzzy command search. Enter runs, Esc backs out."""

    BINDINGS = [
        Binding("escape", "dismiss_cancel", "Close"),
        Binding("down", "list_down", "Next", priority=True),
        Binding("up", "list_up", "Prev", priority=True),
    ]

    CSS = PALETTE_CSS

    def __init__(self, active_tab: str = "cases") -> None:
        super().__init__()
        self._active_tab = active_tab

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-box"):
            with Horizontal(id="palette-head"):
                yield Input(placeholder="Search commands", id="palette-input")
                yield Static("esc", id="palette-esc")
            yield ListView(id="palette-list")

    async def on_mount(self) -> None:
        await self._fill("")
        search = self.query_one("#palette-input", Input)
        search.cursor_blink = False
        search.focus()

    def _search_rows(self, query: str, scoped: list[str]) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        for command in scoped:
            label, hint = _BY_ID[command]
            group, key = COMMAND_META[command]
            candidates.append((f"{command} {label} {hint} {key} {group}", command))
        matches = [command for _, command in filter_completions(candidates, query, limit=12)]
        if not matches:
            return [("head", f'No commands match "{query}"')]
        rows: list[tuple[str, str]] = [("head", "Results")]
        rows.extend(("cmd", command) for command in matches)
        return rows

    def _append_rows(self, view: ListView, rows: list[tuple[str, str]]) -> None:
        for kind, value in rows:
            if kind == "head":
                view.append(ListItem(Static(value, classes="group-label"), disabled=True, classes="group-head"))
                continue
            label = _BY_ID[value][0]
            view.append(
                ListItem(
                    Horizontal(
                        Static(label, classes="cmd-label"),
                        Static(shortcut_label(value), classes="cmd-key"),
                        classes="cmd-columns",
                    ),
                    id=value,
                    classes="cmd-row",
                )
            )

    async def _fill(self, query: str) -> None:
        scoped = [command for command in _BY_ID if command_scope(command) == self._active_tab]
        if query:
            rows = self._search_rows(query, [*scoped, "app-status"])
        else:
            rows = [("head", "In this tab")]
            rows.extend(("cmd", command) for command in scoped)
            rows.append(("head", "Settings"))
            rows.append(("cmd", "app-status"))
        view = self.query_one(PALETTE_LIST_SELECTOR, ListView)
        await view.clear()
        self._append_rows(view, rows)
        view.index = next((index for index, item in enumerate(view.children) if not item.disabled), None)

    def action_list_down(self) -> None:
        self.query_one(PALETTE_LIST_SELECTOR, ListView).action_cursor_down()

    def action_list_up(self) -> None:
        self.query_one(PALETTE_LIST_SELECTOR, ListView).action_cursor_up()

    @on(Input.Changed)
    async def _typed(self, event: Input.Changed) -> None:
        await self._fill(event.value)

    async def _choose(self, target: str | None) -> None:
        self.dismiss(target)

    @on(Input.Submitted)
    async def _submitted(self, event: Input.Submitted) -> None:
        view = self.query_one(PALETTE_LIST_SELECTOR, ListView)
        highlighted = view.highlighted_child
        await self._choose(highlighted.id if highlighted is not None else None)

    @on(ListView.Selected)
    async def _selected(self, event: ListView.Selected) -> None:
        await self._choose(event.item.id if event.item is not None else None)


class KeysModal(_BaseModal, ModalScreen[None]):
    """All keys, grouped. Esc backs out."""

    CSS = """
    KeysModal { align: center middle; }
    #keys-box { width: 68; height: auto; max-height: 26; border: round $panel 50%; background: $surface; padding: 1 2; }
    #keys-box .group-title { color: $accent; text-style: bold; margin-top: 1; }
    #keys-box Static { height: 1; }
    """

    GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
        (
            "Navigation",
            (
                ("1 – 4", "switch tabs  Cases · Devices · Imaging · Audit"),
                ("← / →", "prev / next tab"),
                ("↑ / ↓", "move / select"),
                ("Enter", "open / select"),
                ("Esc", "back / cancel"),
                ("/", "search"),
                ("r", "refresh"),
                ("Ctrl+P", "command palette"),
                ("q", "quit"),
            ),
        ),
        (
            "Cases",
            (
                ("c / e / w", "create · edit · review"),
                ("x / a / p", "seal · archive · purge"),
                ("u", "restore archived"),
                ("r", "recent-first toggle"),
                ("v", "raw JSON drawer"),
            ),
        ),
        (
            "Devices",
            (
                ("i", "inspect device"),
                ("c", "check write protection"),
                ("a", "acknowledge unverified source"),
                ("k", "cycle device kind"),
            ),
        ),
        (
            "Imaging",
            (
                ("n", "reserve an imaging operation"),
                ("a / p", "acquire fixture / physical"),
                ("v", "verify image"),
                ("s / u", "seal / unseal image"),
                ("x", "cancel or abandon"),
                ("c", "choose case"),
            ),
        ),
        (
            "Audit",
            (
                ("s", "scope to case  (Audit)"),
                ("e", "export bundle  (Audit)"),
                ("a", "verify against anchor  (Audit)"),
            ),
        ),
    )

    def compose(self) -> ComposeResult:
        from rich.text import Text
        from textual.containers import VerticalScroll

        from trace_core.core.ui.theme import THEME_HEX

        with Vertical(id="keys-box"):
            yield Label("Keys  (Esc backs out)")
            with VerticalScroll(id="keys-scroll"):
                for title, items in self.GROUPS:
                    yield Static(title, classes="group-title")
                    for key, desc in items:
                        txt = Text()
                        txt.append(f"{key:<12} ", style=f"bold {THEME_HEX['value']}")
                        txt.append(desc, style="dim")
                        yield Static(txt)

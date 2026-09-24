"""Command palette + key map overlay. Fuzzy engine reused from core completion."""

from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from trace_core.core.cli.completion import filter_completions
from trace_core.tui.forms import _BaseModal

if TYPE_CHECKING:
    from trace_core.tui.app import TraceApp

COMMANDS: list[tuple[str, str, str]] = [
    # (command id, label, hint)
    ("tab-cases", "Go: Cases", "case table + dossier"),
    ("tab-audit", "Go: Audit", "ledger stream + detail"),
    ("tab-settings", "Go: Settings", "sections + detail"),
    ("case-create", "Case: create", "guided form"),
    ("case-edit", "Case: edit selected", "diff preview + reason"),
    ("case-close", "Case: seal selected", "type number to confirm"),
    ("case-archive", "Case: archive selected", "y/N confirm"),
    ("case-purge", "Case: purge selected", "type number, irreversible"),
    ("case-restore", "Case: restore selected", "y/N confirm"),
    ("case-recent", "Case: recent first", "5 most recently updated"),
    ("audit-export", "Audit: export bundle", "header + JSONL"),
    ("audit-anchor", "Audit: verify with anchor", "tail check"),
    ("database-migrate", "Database: apply migrations", "pending only"),
]


class PaletteModal(_BaseModal, ModalScreen[str | None]):
    """Fuzzy command search. Enter runs, Esc backs out."""

    CSS = """
    PaletteModal { align: center middle; }
    #palette-box { width: 60; height: auto; max-height: 20; border: solid $panel; background: $surface; padding: 1 2; }
    #palette-list { height: auto; max-height: 14; }
    """

    def __init__(self, app_ref: "TraceApp") -> None:  # noqa: F821
        super().__init__()
        self._app_ref = app_ref

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-box"):
            yield Label("Commands")
            yield Input(placeholder="type to filter…", id="palette-input")
            yield ListView(id="palette-list")

    def on_mount(self) -> None:
        self._fill("")
        self.query_one("#palette-input", Input).focus()

    def _fill(self, query: str) -> None:
        items = filter_completions([(c, f"{label} · {hint}") for c, label, hint in COMMANDS], query, limit=10)
        view = self.query_one("#palette-list", ListView)
        view.clear()
        for cmd, meta in items:
            view.append(ListItem(Static(f"{meta}"), id=f"cmd-{cmd}"))

    @on(Input.Changed)
    def _typed(self, event: Input.Changed) -> None:
        self._fill(event.value)

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        view = self.query_one("#palette-list", ListView)
        highlighted = view.highlighted_child
        target = highlighted.id if highlighted is not None else None
        if target is None and view.children:
            target = view.children[0].id
        self.dismiss(target.removeprefix("cmd-") if target else None)

    @on(ListView.Selected)
    def _selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id if event.item is not None else None
        self.dismiss(item_id.removeprefix("cmd-") if item_id else None)


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
                ("1 – 3", "switch tabs  Cases · Audit · Settings"),
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
                ("c / e / x / a / p", "create · edit · seal · archive · purge"),
                ("u", "restore archived"),
                ("r", "recent-first toggle"),
                ("v", "raw JSON drawer"),
            ),
        ),
        (
            "Audit · Settings",
            (
                ("s", "scope to case  (Audit)"),
                ("e", "export bundle  (Audit)"),
                ("m", "apply migrations  (Settings · Database)"),
                ("c", "check updates  (Settings · Updates)"),
                ("v", "verify chain  (Settings · Integrity)"),
            ),
        ),
    )

    # kept for tests that import KEYS
    KEYS: tuple[tuple[str, str], ...] = tuple(k for _, g in GROUPS for k in g)

    def compose(self) -> ComposeResult:
        from rich.text import Text
        from textual.containers import VerticalScroll

        with Vertical(id="keys-box"):
            yield Label("Keys  (Esc backs out)")
            with VerticalScroll(id="keys-scroll"):
                for title, items in self.GROUPS:
                    yield Static(title, classes="group-title")
                    for key, desc in items:
                        txt = Text()
                        txt.append(f"{key:<12} ", style="bold #E5EAF0")
                        txt.append(desc, style="dim")
                        yield Static(txt)

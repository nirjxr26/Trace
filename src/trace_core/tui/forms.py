"""Modal forms for case mutations. Same confirms as CLI: typed number for destructive.

Every modal backs out on Esc with cancel semantics. Scrollable bodies keep buttons
reachable on short terminals.
"""

from collections.abc import Callable

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, Input, Label, ListView, Static

from trace_core.tui.design.css import MODAL_CSS_PREFIX
from trace_core.tui.design.widgets import FlatButton, ModalFrame
from trace_core.tui.theme import SELECT_PREFIX

ESCAPES: list[Binding | tuple[str, str] | tuple[str, str, str]] = [("escape", "dismiss_cancel", "Back")]


class _BaseModal(ModalScreen):
    """Centered, Esc-dismissable, round-bordered. Single source for all modals."""

    # Copied per class: assigning the shared list by reference meant an append on one
    # subclass mutated every other modal's bindings.
    BINDINGS = list(ESCAPES)

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)


FIELD_LABELS: dict[str, str] = {
    "title": "Title *",
    "examiner": "Lead examiner *",
    "number": "Number (blank = auto)",
    "tags": "Tags (comma-separated)",
    "reason": "Reason (why)",
    "description": "Description",
    "notes": "Notes",
}


class CaseForm(_BaseModal):
    """Create/edit form. Returns field values or None on cancel."""

    CSS = (
        MODAL_CSS_PREFIX
        + """
    CaseForm { align: center middle; }
    #case-form { width: 76; height: auto; max-height: 90%; border: none; background: $elevated; padding: 0; }
    #case-form #case-heading { width: 1fr; height: auto; padding: 1 3; color: $accent; text-style: bold; background: $form-bg; content-align: left middle; margin-bottom: 1; }
    #case-fields { height: auto; max-height: 18; padding: 1 3; scrollbar-gutter: stable; }
    #case-form Input { width: 1fr; height: 1; border: none; background: transparent; padding: 0 1; }
    #case-form Input:focus { border: none; background: transparent; background-tint: transparent; }
    #case-buttons { align: center middle; height: auto; padding-bottom: 1; }
    #case-buttons Button { border: none; background: $panel; background-tint: transparent; color: $text; min-width: 20; height: 3; padding: 0 4; margin: 0 1; text-align: center; content-align: center middle; text-style: bold; }
    #case-buttons Button:hover, #case-buttons Button:focus { border: none; background: $panel; background-tint: transparent; color: $accent; text-style: bold; }
    """
    )

    CREATE_FIELDS: tuple[tuple[str, str], ...] = (
        ("title", FIELD_LABELS["title"]),
        ("examiner", FIELD_LABELS["examiner"]),
        ("number", FIELD_LABELS["number"]),
        ("tags", FIELD_LABELS["tags"]),
        ("description", FIELD_LABELS["description"]),
        ("notes", FIELD_LABELS["notes"]),
    )
    EDIT_FIELDS: tuple[tuple[str, str], ...] = (
        ("title", FIELD_LABELS["title"]),
        ("examiner", FIELD_LABELS["examiner"]),
        ("tags", FIELD_LABELS["tags"]),
        ("reason", FIELD_LABELS["reason"]),
        ("description", FIELD_LABELS["description"]),
        ("notes", FIELD_LABELS["notes"]),
    )

    def __init__(
        self, heading: str = "New case", initial: dict[str, str] | None = None, for_create: bool = True
    ) -> None:
        super().__init__()
        self._heading = heading
        self._initial = initial or {}
        self._for_create = for_create
        self._fields = self.CREATE_FIELDS if for_create else self.EDIT_FIELDS

    def compose(self) -> ComposeResult:
        with ModalFrame(widget_id="case-form"):
            yield Label("CREATE CASE" if self._for_create else "EDIT CASE", id="case-heading")
            with VerticalScroll(id="case-fields"):
                for key, label in self._fields:
                    with Horizontal(classes="modal-field-row"):
                        yield Static(f"{label:<23}:", classes="modal-field-label")
                        yield Input(value=self._initial.get(key, ""), id=f"field-{key}", classes="modal-input")
            with Horizontal(id="case-buttons"):
                yield FlatButton("Save", id="save", classes="modal-button")
                yield FlatButton("Cancel", id="cancel", classes="modal-button")

    def on_mount(self) -> None:
        self.query_one("#field-title", Input).focus()

    @on(Input.Submitted)
    def _next_field(self, event: Input.Submitted) -> None:
        """Enter moves to the next field; on the last field it saves."""
        event.stop()
        keys = [key for key, _ in self._fields]
        try:
            current = (event.input.id or "").removeprefix("field-")
            nxt = keys[keys.index(current) + 1]
        except (ValueError, IndexError):
            nxt = ""
        if nxt:
            self.query_one(f"#field-{nxt}", Input).focus()
        else:
            self._save()

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        values = {key: self.query_one(f"#field-{key}", Input).value.strip() for key, _ in self._fields}
        values.setdefault("number", "")
        values.setdefault("reason", "")
        if not values["title"] or not values["examiner"]:
            self.app.notify("Title and examiner are required.", severity="error")
            return
        self.dismiss(values)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


def _pretty_json(body: str) -> str:
    import json

    try:
        return json.dumps(json.loads(body), indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return body


class RawModal(_BaseModal):
    """Scrollable raw JSON drawer. Esc backs out."""

    CSS = (
        MODAL_CSS_PREFIX
        + """
    RawModal { align: center middle; }
    #raw-box { width: 90%; height: 90%; }
    #raw-body { height: 1fr; }
    """
    )

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll
        from textual.widgets import Static

        with ModalFrame(widget_id="raw-box"):
            yield Label(self._title)
            with VerticalScroll(id="raw-body"):
                yield Static(_pretty_json(self._body))


class TextInputModal(_BaseModal):
    """Single path/value prompt. Returns stripped text or None on cancel."""

    CSS = (
        MODAL_CSS_PREFIX
        + """
    TextInputModal { align: center middle; }
    #text-box { width: 64; height: auto; border: none; background: $elevated; padding: 2 3; }
    #text-box Label { height: 1; color: $text; text-style: bold; }
    .text-input-row { height: 1; align: center middle; margin-top: 1; }
    .input-caret { width: 2; color: $accent; }
    #text-box Input { border: none; background: transparent; padding: 0 1; }
    #text-box Input:focus { border: none; background: transparent; background-tint: transparent; }
    #text-box Input.second { margin-top: 1; }
    .text-buttons { height: 3; align: center middle; margin-top: 1; }
    #text-box Button { border: none; background: $panel; background-tint: transparent; color: $text; width: 18; min-width: 18; height: 3; text-align: center; content-align: center middle; text-style: bold; }
    #text-box Button:hover, #text-box Button:focus { border: none; background: $panel; background-tint: transparent; color: $accent; }
    #text-box .modal-button { margin: 0 1; }
    """
    )

    def __init__(
        self,
        title: str,
        placeholder: str = "",
        required: bool = False,
        password: bool = False,
        confirm: bool = False,
    ) -> None:
        super().__init__()
        self._title = title if not required else f"{title}*"
        self._placeholder = placeholder
        self._required = required
        self._password = password
        self._confirm = confirm

    def compose(self) -> ComposeResult:
        with ModalFrame(widget_id="text-box"):
            yield Label(self._title)
            with Horizontal(classes="text-input-row"):
                yield Static(SELECT_PREFIX, classes="input-caret")
                yield Input(
                    placeholder=self._placeholder,
                    id="text-input",
                    password=self._password,
                    classes="modal-input",
                )
            if self._confirm:
                with Horizontal(classes="text-input-row"):
                    yield Static(SELECT_PREFIX, classes="input-caret")
                    yield Input(
                        placeholder="Repeat passphrase",
                        id="text-confirm",
                        password=True,
                        classes="second modal-input",
                    )
            with Horizontal(classes="text-buttons"):
                yield FlatButton("Ok", id="ok", classes="modal-button")
                yield FlatButton("Cancel", id="cancel", classes="modal-button")

    def on_mount(self) -> None:
        self.query_one("#text-input", Input).focus()

    @on(Input.Submitted, "#text-input")
    def _advance(self) -> None:
        if self._confirm:
            self.query_one("#text-confirm", Input).focus()
            return
        self._ok()

    @on(Button.Pressed, "#ok")
    @on(Input.Submitted, "#text-confirm")
    def _ok(self) -> None:
        value = self.query_one("#text-input", Input).value.strip()
        if self._required and not value:
            self.app.notify("A value is required.", severity="warning")
            return
        if self._confirm:
            repeated = self.query_one("#text-confirm", Input).value.strip()
            if value != repeated:
                self.app.notify("Passphrases do not match.", severity="warning")
                return
        self.dismiss(value or None)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class ExportHubModal(_BaseModal):
    CSS = (
        MODAL_CSS_PREFIX
        + """
    ExportHubModal { align: center middle; }
    #export-box { width: 72; height: auto; border: none; background: $elevated; padding: 0; }
    #export-head { height: auto; background: $form-bg; padding: 1 3; }
    #export-title { color: $accent; text-style: bold; }
    #export-body { height: auto; padding: 1 3 1 3; }
    #export-scope { color: $muted; margin-bottom: 1; }
    #export-list { height: 3; background: transparent; scrollbar-size-vertical: 0; scrollbar-size-horizontal: 0; }
    #export-list > ListItem { background: transparent; padding: 0; }
    #export-list > ListItem.-highlight { background: transparent; }
    .export-row { height: 1; }
    .export-caret { width: 2; color: $accent; }
    .export-label { width: 24; color: $text; text-style: bold; }
    .export-note { color: $muted; }
    """
    )

    CHOICES = (
        ("plain", "Bundle (JSONL)", "plain, readable"),
        ("sealed", "Sealed bundle", "passphrase protected"),
        ("open", "Open a sealed bundle", "decrypt to JSONL"),
    )

    def __init__(self, scope: str = "") -> None:
        super().__init__()
        self._scope = scope
        self._carets: list[Static] = []

    def compose(self) -> ComposeResult:
        with ModalFrame(widget_id="export-box"):
            with Vertical(id="export-head"):
                yield Label("Export", id="export-title")
            with Vertical(id="export-body"):
                if self._scope:
                    yield Static(self._scope, id="export-scope")
                yield ListView(id="export-list")

    def on_mount(self) -> None:
        from textual.widgets import ListItem

        listing = self.query_one("#export-list", ListView)
        for _, label, note in self.CHOICES:
            caret = Static("", classes="export-caret")
            self._carets.append(caret)
            listing.append(
                ListItem(
                    Horizontal(
                        caret,
                        Static(label, classes="export-label"),
                        Static(note, classes="export-note"),
                        classes="export-row",
                    )
                )
            )
        listing.index = 0
        self._render_carets(0)
        listing.focus()

    def _render_carets(self, selected: int) -> None:
        for index, caret in enumerate(self._carets):
            caret.update(SELECT_PREFIX if index == selected else "  ")

    @on(ListView.Highlighted, "#export-list")
    def _highlighted(self, event: ListView.Highlighted) -> None:
        index = event.list_view.index
        if index is not None:
            self._render_carets(index)

    @on(ListView.Selected, "#export-list")
    def _picked(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None and 0 <= index < len(self.CHOICES):
            self.dismiss(self.CHOICES[index][0])


class TypedConfirmModal(_BaseModal):
    """Type-the-number confirm for close/purge. Returns True only on exact match."""

    CSS = (
        MODAL_CSS_PREFIX
        + """
    TypedConfirmModal { align: center middle; }
    #confirm-box { width: 50; height: auto; border: none; background: $elevated; padding: 1 3 0 3; }
    #confirm-box Horizontal { align: center middle; height: auto; margin-top: 1; }
    #confirm-box Input { height: 3; margin: 1 0; border: none; }
    #confirm-box Input:focus { border: none; background: transparent; background-tint: transparent; }
    """
    )

    def __init__(self, prompt: str, expected: str, note: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._expected = expected
        self._note = note

    def action_dismiss_cancel(self) -> None:
        self.dismiss(False)

    def compose(self) -> ComposeResult:
        with ModalFrame(widget_id="confirm-box"):
            yield Static(self._prompt, classes="confirm-prompt")
            if self._note:
                yield Static(self._note, classes="muted")
            yield Input(placeholder=self._expected, id="confirm-input", classes="confirm-input")
            with Horizontal():
                yield FlatButton("Yes", id="ok", classes="confirm-button")
                yield FlatButton("No", id="cancel", classes="confirm-button")

    def on_mount(self) -> None:
        self.query_one("#confirm-input", Input).focus()

    @on(Button.Pressed, "#ok")
    @on(Input.Submitted)
    def _confirm(self) -> None:
        typed = self.query_one("#confirm-input", Input).value.strip()
        if typed != self._expected.strip():
            self.app.notify("Mismatch — cancelled.", severity="warning")
            self.dismiss(False)
            return
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(False)


class YesNoModal(_BaseModal):
    """y/N confirm for archive/restore. Returns True on yes."""

    CSS = (
        MODAL_CSS_PREFIX
        + """
    YesNoModal { align: center middle; }
    #yesno-box { width: 50; height: auto; border: none; background: $elevated; padding: 1 3; align: center middle; }
    #yesno-box Horizontal { align: center middle; height: auto; margin-top: 1; }
    """
    )

    def __init__(self, prompt: str | Text) -> None:
        super().__init__()
        self._prompt = prompt

    def action_dismiss_cancel(self) -> None:
        self.dismiss(False)

    def compose(self) -> ComposeResult:
        with ModalFrame(widget_id="yesno-box"):
            yield Static(self._prompt, classes="confirm-prompt")
            with Horizontal():
                yield FlatButton("Yes", id="yes", classes="confirm-button")
                yield FlatButton("No", id="no", classes="confirm-button")

    def on_mount(self) -> None:
        # Default to No. Without this, focus lands on the first focusable widget
        # (#yes), so Enter immediately confirmed an archive or restore.
        self.query_one("#no", Button).focus()

    @on(Button.Pressed, "#yes")
    def _yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def _no(self) -> None:
        self.dismiss(False)


class CasePicker(_BaseModal):
    """Searchable chooser over a caller-supplied loader. Returns the chosen key, or None.

    A text box was rejected: an operator standing at a bagged drive knows the case, not
    its number, and the number is a lookup. Rows carry the title so the choice is made
    by name. Composed from the ListView + Input the Cases tab already uses.
    """

    CSS = (
        MODAL_CSS_PREFIX
        + """
    CasePicker { align: center middle; }
    #case-pick-box { width: 70; height: auto; border: none; background: $elevated; padding: 0; }
    #case-pick-head { height: auto; background: $form-bg; padding: 1 3; }
    #case-pick-box #case-pick-title { height: 1; color: $accent; text-style: bold; }
    #case-pick-search { height: 1; align: center middle; margin: 1 3 0 3; }
    #case-pick-caret { width: 2; color: $accent; }
    #case-pick-box Input { border: none; height: 1; background: transparent; padding: 0; }
    #case-pick-box Input:focus { border: none; background: transparent; background-tint: transparent; }
    #case-pick-list { height: 10; background: transparent; padding: 1 3; scrollbar-size-vertical: 0; scrollbar-size-horizontal: 0; }
    #case-pick-list > ListItem { background: transparent; }
    #case-pick-list > ListItem.-highlight { background: $surface-active; }
    #case-pick-empty { color: $muted; height: 1; padding: 0 3; }
    """
    )

    def __init__(self, load: Callable[[str], list[tuple[str, str]]], title: str = "Choose an item") -> None:
        super().__init__()
        self._load = load
        self._title = title
        self._rows: list[tuple[str, str]] = []
        self._pending = ""
        self._search_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        from textual.widgets import Input, ListView

        with ModalFrame(widget_id="case-pick-box"):
            with Vertical(id="case-pick-head"):
                yield Label(self._title, id="case-pick-title")
            with Horizontal(id="case-pick-search"):
                yield Static("› ", id="case-pick-caret")
                yield Input(placeholder="search or filter case", id="case-pick-filter", classes="modal-input")
            yield ListView(id="case-pick-list")
            yield Static("", id="case-pick-empty")

    def on_mount(self) -> None:
        self._rebuild("")
        self.query_one("#case-pick-filter", Input).focus()

    def _rebuild(self, term: str) -> None:
        from textual.widgets import ListItem, ListView

        try:
            self._rows = self._load(term.strip())
        except Exception as exc:  # boundary: a failed lookup must not kill the modal
            self._rows = []
            self.query_one("#case-pick-list", ListView).clear()
            self.query_one("#case-pick-empty", Static).update(f"  {exc}")
            return
        listing = self.query_one("#case-pick-list", ListView)
        listing.clear()
        for number, title in self._rows:
            listing.append(ListItem(Label(f"{number:<22}{title}".rstrip())))
        listing.index = 0 if self._rows else None
        self.query_one("#case-pick-empty", Static).update("" if self._rows else "  no case matches")

    @on(Input.Changed, "#case-pick-filter")
    def _filtered(self, event: Input.Changed) -> None:
        self._pending = event.value
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.25, self._apply_pending)

    def _apply_pending(self) -> None:
        self._rebuild(self._pending)

    def _flush_pending(self) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
            self._rebuild(self._pending)

    @on(Input.Submitted, "#case-pick-filter")
    def _submitted(self, event: Input.Submitted) -> None:
        self._flush_pending()
        if self._rows:
            self.dismiss(self._rows[0][0])

    @on(ListView.Selected, "#case-pick-list")
    def _chosen(self, event: ListView.Selected) -> None:
        self._flush_pending()
        if event.list_view.index is not None and 0 <= event.list_view.index < len(self._rows):
            self.dismiss(self._rows[event.list_view.index][0])

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        """Hand the first Down to the list, then let the list own the arrow keys.

        Stopping every "down" swallowed the event before ListView could move its cursor,
        so the list could be focused but never traversed.
        """
        if event.key == "down" and self.query_one("#case-pick-filter", Input).has_focus:
            self.query_one("#case-pick-list", ListView).focus()
            event.stop()

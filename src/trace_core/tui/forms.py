"""Modal forms for case mutations. Same confirms as CLI: typed number for destructive.

Every modal backs out on Esc with cancel semantics. Scrollable bodies keep buttons
reachable on short terminals.
"""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

ESCAPES: list[Binding | tuple[str, str] | tuple[str, str, str]] = [("escape", "dismiss_cancel", "Back")]


class _BaseModal(ModalScreen):
    """Centered, Esc-dismissable, round-bordered. Single source for all modals."""

    BINDINGS = ESCAPES  # type: ignore[assignment]

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)  # type: ignore[attr-defined]


FIELD_LABELS: dict[str, str] = {
    "title": "Title *",
    "examiner": "Lead examiner *",
    "number": "Number (blank = auto)",
    "tags": "Tags (comma-separated)",
    "reason": "Reason (why)",
    "description": "Description",
    "notes": "Notes",
}


class CaseForm(_BaseModal, ModalScreen[dict[str, str] | None]):
    """Create/edit form. Returns field values or None on cancel."""

    BINDINGS = ESCAPES

    CSS = """
    CaseForm { align: center middle; }
    #case-form { width: 84; height: auto; max-height: 90%; border: round $panel 50%; background: $surface; padding: 1 2; }
    #case-form Input { border: round $panel; height: 3; }
    #case-form Label { height: 1; margin: 0; color: $text-muted; }
    #case-fields { layout: grid; grid-size: 2; grid-gutter: 1 1; height: auto; max-height: 22; scrollbar-gutter: stable; }
    .field-col { width: 1fr; height: 4; }
    .field-full { width: 1fr; height: 4; column-span: 2; }
    #case-heading { text-align: center; color: $accent; text-style: bold underline; height: 3; content-align: center middle; background: $surface; }
    #case-buttons { align: center middle; height: 3; dock: bottom; margin-top: 1; }
    #case-buttons Button { border: round $panel; margin: 0 2; min-width: 18; height: 3; content-align: center middle; }
    """

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
        self._fields = self.CREATE_FIELDS if for_create else self.EDIT_FIELDS

    def compose(self) -> ComposeResult:
        with Vertical(id="case-form"):
            yield Label(self._heading.upper(), id="case-heading")
            with VerticalScroll(id="case-fields"):
                fields = list(self._fields)
                for idx, (key, label) in enumerate(fields):
                    # first 4 as 2-col grid cells, last 2 as full-width
                    cls = "field-col" if idx < 4 else "field-full"
                    with Vertical(classes=cls):
                        yield Label(label)
                        yield Input(value=self._initial.get(key, ""), id=f"field-{key}")
            with Horizontal(id="case-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel (Esc)", id="cancel")

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


class RawModal(_BaseModal, ModalScreen[None]):
    """Scrollable raw JSON drawer. Esc backs out."""

    CSS = """
    RawModal { align: center middle; }
    #raw-box { width: 90%; height: 90%; border: round $panel 50%; background: $surface; padding: 1 2; }
    #raw-body { height: 1fr; }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll
        from textual.widgets import Static

        with Vertical(id="raw-box"):
            yield Label(self._title)
            with VerticalScroll(id="raw-body"):
                yield Static(self._body)


class TextInputModal(_BaseModal, ModalScreen[str | None]):
    """Single path/value prompt. Returns stripped text or None on cancel."""

    CSS = """
    TextInputModal { align: center middle; }
    #text-box { width: 64; height: auto; border: round $panel 50%; background: $surface; padding: 1 2; }
    #text-box Input { border: round $panel; height: 3; }
    #text-box Horizontal { align: center middle; height: 3; margin-top: 1; }
    #text-box Button { border: round $panel; min-width: 16; height: 3; }
    """

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="text-box"):
            yield Label(self._title)
            yield Input(placeholder=self._placeholder, id="text-input")
            with Horizontal():
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#text-input", Input).focus()

    @on(Button.Pressed, "#ok")
    @on(Input.Submitted)
    def _ok(self) -> None:
        value = self.query_one("#text-input", Input).value.strip()
        self.dismiss(value or None)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class TypedConfirmModal(_BaseModal, ModalScreen[bool]):
    """Type-the-number confirm for close/purge. Returns True only on exact match."""

    CSS = """
    TypedConfirmModal { align: center middle; }
    #confirm-box { width: 60; height: auto; border: round $error 60%; background: $surface; padding: 1 2; }
    #confirm-box Horizontal { align: center middle; height: auto; margin-top: 1; }
    #confirm-box Button { border: round $panel; min-width: 16; height: 3; content-align: center middle; margin: 0 2; }
    #confirm-box Input { border: round $panel; height: 3; margin: 1 0; }
    """

    def __init__(self, prompt: str, expected: str, note: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._expected = expected
        self._note = note

    def action_dismiss_cancel(self) -> None:
        self.dismiss(False)

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._prompt)
            if self._note:
                yield Static(self._note, classes="muted")
            yield Input(placeholder=self._expected, id="confirm-input")
            with Horizontal():
                yield Button("Confirm", variant="error", id="ok")
                yield Button("Cancel", id="cancel")

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


class YesNoModal(_BaseModal, ModalScreen[bool]):
    """y/N confirm for archive/restore. Returns True on yes."""

    CSS = """
    YesNoModal { align: center middle; }
    #yesno-box { width: 56; height: auto; border: round $panel 50%; background: $surface; padding: 1 2; align: center middle; }
    #yesno-box Horizontal { align: center middle; height: auto; margin-top: 1; }
    #yesno-box Button { border: round $panel; min-width: 16; height: 3; content-align: center middle; margin: 0 2; }
    """

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def action_dismiss_cancel(self) -> None:
        self.dismiss(False)

    def compose(self) -> ComposeResult:
        with Vertical(id="yesno-box"):
            yield Static(self._prompt)
            with Horizontal():
                yield Button("Yes", variant="primary", id="yes")
                yield Button("No", id="no")

    @on(Button.Pressed, "#yes")
    def _yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def _no(self) -> None:
        self.dismiss(False)

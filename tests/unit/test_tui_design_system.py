import inspect
import re
from pathlib import Path

from trace_core.core.ui.theme import THEME_HEX
from trace_core.tui.design.css import APP_CSS, MODAL_CSS_PREFIX
from trace_core.tui.design.widgets import FlatButton, ListDetailPane
from trace_core.tui.theme import TRACE_THEME

TUI_ROOT = Path(__file__).resolve().parents[2] / "src" / "trace_core" / "tui"
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def _sources() -> list[Path]:
    return sorted(TUI_ROOT.rglob("*.py"))


def test_no_literal_hex_in_tui() -> None:
    for source in _sources():
        assert not HEX.search(source.read_text(encoding="utf-8")), source


def test_no_split_muted_token() -> None:
    for source in _sources():
        assert "$text-muted" not in source.read_text(encoding="utf-8"), source


def test_shared_css_classes_are_defined() -> None:
    for selector in (
        ".pane",
        ".pane-left",
        ".pane-right",
        ".pane-search",
        ".pane-table",
        ".pane-rule",
        ".modal-box",
        ".modal-input",
        ".modal-button",
        ".modal-actions",
    ):
        assert selector in APP_CSS


def test_shared_css_classes_are_applied() -> None:
    pane_source = inspect.getsource(ListDetailPane)
    for applied in (
        'classes="pane-host"',
        'classes="pane pane-left"',
        'classes="pane pane-right"',
        'classes="pane-search"',
        'classes="pane-rule"',
    ):
        assert applied in pane_source

    forms_source = (TUI_ROOT / "forms.py").read_text(encoding="utf-8")
    assert forms_source.count("with ModalFrame(") >= 7
    assert 'classes="modal-input"' in forms_source
    assert 'classes="modal-button"' in forms_source
    assert (
        "#case-form Input:focus { border: none; background: transparent; background-tint: transparent; }"
        in forms_source
    )
    assert "#case-form #case-heading" in forms_source
    assert 'yield Label("CREATE CASE" if self._for_create else "EDIT CASE", id="case-heading")' in forms_source
    assert 'classes="modal-field-row"' in forms_source
    assert 'classes="modal-field-label"' in forms_source
    assert 'yield FlatButton("Save", id="save"' in forms_source
    assert 'yield FlatButton("Cancel", id="cancel"' in forms_source
    assert forms_source.count("yield FlatButton(") >= 8
    assert "yield Button(" not in forms_source
    assert "Button.modal-button:hover" in APP_CSS
    assert "Button.confirm-button:hover" in APP_CSS
    flat_source = inspect.getsource(FlatButton)
    assert "self.styles.line_pad = 0" in flat_source
    assert "self.styles.height = 3" in flat_source
    assert 'self.styles.text_align = "center"' in flat_source
    assert 'self.styles.content_align = ("center", "middle")' in flat_source
    assert ".confirm-button" in APP_CSS
    assert (
        "Button.confirm-button:hover, Button.confirm-button:focus { border: none; background: $panel; background-tint: transparent; color: $accent; text-style: bold; }"
        in APP_CSS
    )
    assert 'yield Static(self._prompt, classes="confirm-prompt")' in forms_source
    assert "#confirm-box { width: 50;" in forms_source
    assert "#yesno-box { width: 50;" in forms_source
    assert 'f"{label:<23}:' in forms_source
    assert THEME_HEX["form_bg"] == "#141414"
    assert "$form-bg" in MODAL_CSS_PREFIX
    assert "form-bg" in TRACE_THEME.variables

    for name in ("cases", "audit", "devices", "imaging"):
        screen_source = (TUI_ROOT / "screens" / f"{name}.py").read_text(encoding="utf-8")
        assert "ListDetailPane(" in screen_source
        assert 'classes="pane-table"' in screen_source

    settings_source = (TUI_ROOT / "screens" / "settings.py").read_text(encoding="utf-8")
    assert 'classes="pane-host"' in settings_source
    assert 'classes="pane pane-left"' in settings_source
    assert 'classes="pane pane-right"' in settings_source

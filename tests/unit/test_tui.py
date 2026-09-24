"""Pilot tests for the fullscreen console: mount, navigate, dossier, verify, db."""

import pytest
from rich.text import Text

from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.app import TraceApp

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture(params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    """AnyIO backend for Textual pilot tests."""
    return request.param


@pytest.fixture
def seeded_manager(session_manager: DatabaseSessionManager) -> DatabaseSessionManager:
    """Two cases (one edited) in the shared in-memory database."""
    from datetime import UTC, datetime, timedelta

    from trace_core.core.clock import reset_clock, set_clock

    class _TickClock:
        def __init__(self) -> None:
            self.now_value = datetime(2026, 1, 1, tzinfo=UTC)

        def now(self) -> datetime:
            self.now_value += timedelta(seconds=1)
            return self.now_value

    set_clock(_TickClock())
    try:
        svc = CaseService(session_manager)
        svc.create_case(CaseCreateDto(title="Alpha", lead_examiner="Ex"))
        created = svc.create_case(CaseCreateDto(title="Beta", lead_examiner="Ex"))
        from trace_core.cases.dto import CaseUpdateDto

        svc.update_case(created.number, CaseUpdateDto(notes="touched"))
        return session_manager
    finally:
        reset_clock()


def _text(widget) -> str:  # type: ignore[no-untyped-def]
    renderable = widget.render()
    return renderable.plain if isinstance(renderable, Text) else str(renderable)


async def test_tui_pilot_flow(seeded_manager: DatabaseSessionManager) -> None:
    """Mount → cases listed → cursor moves dossier → audit → settings sections."""
    from textual.widgets import DataTable, Static, TabbedContent

    app = TraceApp(seeded_manager)
    async with app.run_test(size=(110, 30)) as pilot:
        table = app.query_one("#case-table", DataTable)
        assert table.row_count == 2
        # ensure table has focus so arrows move the cursor, not the tab bar
        table.focus()
        await pilot.pause()
        assert "Beta" in _text(app.query_one("#case-dossier", Static))
        await pilot.pause()
        shot = app.export_screenshot()
        assert "2026-CR-" in shot
        assert "Case" in shot and "Status" in shot
        assert "─" in shot

        await pilot.press("down")
        await pilot.pause()
        assert "Alpha" in _text(app.query_one("#case-dossier", Static))

        await pilot.press("2")
        await pilot.pause()
        assert app.query_one(TabbedContent).active == "audit"
        assert "Audit" in app.export_screenshot()
        audit_table = app.query_one("#audit-table", DataTable)
        assert audit_table.row_count == 3
        assert len(audit_table.columns) == 2
        assert "Case details updated" in _text(app.query_one("#audit-detail", Static))
        assert "Seq" in app.export_screenshot()

        await pilot.press("3")
        await pilot.pause()
        assert app.query_one(TabbedContent).active == "settings"
        assert "Settings" in app.export_screenshot()
        from textual.widgets import ListView

        sections = app.query_one("#settings-sections", ListView)
        assert len(list(sections.children)) == 7
        assert "Database" in _text(app.query_one("#settings-detail", Static))
        assert "Online" in _text(app.query_one("#settings-detail", Static))

        await pilot.press("down")
        await pilot.pause()
        detail = _text(app.query_one("#settings-detail", Static))
        assert "Previous" in detail and "Status" in detail

        await pilot.press("down")
        await pilot.pause()
        assert "VALID" in _text(app.query_one("#settings-detail", Static))


async def test_modals_back_out_on_escape(seeded_manager: DatabaseSessionManager) -> None:
    """Every modal backs out on Esc — nobody gets stuck in a form."""
    from trace_core.tui.forms import CaseForm, TypedConfirmModal, YesNoModal
    from trace_core.tui.palette import KeysModal, PaletteModal

    app = TraceApp(seeded_manager)
    async with app.run_test() as pilot:
        for modal in (
            CaseForm(),
            TypedConfirmModal("Seal?", "2026-CR-0001"),
            YesNoModal("Archive?"),
            KeysModal(),
            PaletteModal(app),
        ):
            app.push_screen(modal)
            await pilot.pause()
            assert app.screen is modal
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, type(modal))


async def test_case_form_typing_and_enter_flow() -> None:
    """Focus lands in Title, typing works, Enter advances, last Enter saves."""
    from textual.app import App, ComposeResult
    from textual.widgets import Button

    from trace_core.tui.forms import CaseForm

    class _Host(App[None]):
        def __init__(self) -> None:
            super().__init__()
            self.result: object = "unset"

        def compose(self) -> ComposeResult:
            yield Button("open", id="open")

        def on_mount(self) -> None:
            self.push_screen(CaseForm(), self._done)

        def _done(self, result: object) -> None:
            self.result = result

    app = _Host()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert getattr(app.focused, "id", None) == "field-title"
        await pilot.press(*list("T"), "enter", *list("E"), "enter", "enter", "enter", "enter", "enter")
        await pilot.pause()
        assert isinstance(app.result, dict)
        assert (app.result["title"], app.result["examiner"]) == ("T", "E")


async def test_tui_palette_routing(seeded_manager: DatabaseSessionManager) -> None:
    """Palette command ids route to tabs without typing."""
    from textual.widgets import TabbedContent

    app = TraceApp(seeded_manager)
    async with app.run_test():
        app._palette_done("tab-settings")
        await app.workers.wait_for_complete()
        assert app.query_one(TabbedContent).active == "settings"
        app._palette_done("tab-integrity")
        await app.workers.wait_for_complete()
        assert app.query_one(TabbedContent).active == "settings"
        app._palette_done("tab-database")
        await app.workers.wait_for_complete()
        assert app.query_one(TabbedContent).active == "settings"
        app._palette_done(None)
        app._palette_done("no-such-command")

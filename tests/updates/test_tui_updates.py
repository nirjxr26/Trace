import pytest
from rich.text import Text
from textual.widgets import ListView, Static

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.app import TraceApp
from trace_core.tui.status import StatusModal

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def _text(widget) -> str:  # type: ignore[no-untyped-def]
    renderable = widget.render()
    return renderable.plain if isinstance(renderable, Text) else str(renderable)


async def _open_updates(pilot, app) -> StatusModal:  # type: ignore[no-untyped-def]
    app._palette_done("app-status")
    await pilot.pause()
    modal = app.screen
    assert isinstance(modal, StatusModal)
    modal.query_one("#palette-list", ListView).index = 1
    await pilot.press("enter")
    await pilot.pause()
    assert app.screen is modal
    assert "Settings" in _text(modal.query_one("#status-title", Static))
    return modal


async def _wait_detail(pilot, modal, needle: str) -> str:  # type: ignore[no-untyped-def]
    for _ in range(30):
        await pilot.pause()
        text = _text(modal.query_one("#status-detail", Static))
        if needle in text:
            return text
    return _text(modal.query_one("#status-detail", Static))


async def test_check_updates_shows_static_status_first(session_manager: DatabaseSessionManager) -> None:
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        modal = await _open_updates(pilot, app)
        assert "Checking for updates…" in _text(modal.query_one("#status-detail", Static))
        assert not modal.query("#update-apply")


async def test_check_updates_reports_available_version(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.updates import checker

    calls: list[int] = []

    def peek():  # type: ignore[no-untyped-def]
        calls.append(1)
        return {"target": "1.5.0"}

    monkeypatch.setattr(checker, "peek_cached_update", peek)
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        modal = await _open_updates(pilot, app)
        text = await _wait_detail(pilot, modal, "Update available to 1.5.0")
        assert "trace update install" in text
        assert calls


async def test_check_updates_reports_system_up_to_date(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.updates import checker

    monkeypatch.setattr(checker, "peek_cached_update", lambda: {"target": ""})
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        modal = await _open_updates(pilot, app)
        text = await _wait_detail(pilot, modal, "Update not available")
        assert "install" not in text.lower()


async def test_check_updates_failure_is_sanitized(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.updates import checker

    def fail():  # type: ignore[no-untyped-def]
        raise OSError("secret-path/boom")

    monkeypatch.setattr(checker, "peek_cached_update", fail)
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        modal = await _open_updates(pilot, app)
        text = await _wait_detail(pilot, modal, "Check failed")
        assert "boom" in text


async def test_escape_returns_to_status_rows(session_manager: DatabaseSessionManager) -> None:
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        modal = await _open_updates(pilot, app)
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is modal
        assert modal.query_one("#palette-list", ListView).display
        assert not modal.query_one("#status-detail", Static).display


async def test_settings_tab_is_gone(session_manager: DatabaseSessionManager) -> None:
    from textual.widgets import TabbedContent

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("5")
        await pilot.pause()
        assert app.query_one(TabbedContent).active != "settings"

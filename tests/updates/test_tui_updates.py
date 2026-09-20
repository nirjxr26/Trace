import pytest
from rich.text import Text

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.app import TraceApp

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture(params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    return request.param


def _text(widget) -> str:  # type: ignore[no-untyped-def]
    renderable = widget.render()
    return renderable.plain if isinstance(renderable, Text) else str(renderable)


async def test_updates_tab_check_and_hint(session_manager: DatabaseSessionManager, signed_release, monkeypatch) -> None:
    from textual.widgets import Static, TabbedContent

    from trace_core.core.settings import settings

    _, manifest_path, _, _ = signed_release()
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("5")
        await pilot.pause()
        assert app.query_one(TabbedContent).active == "updates"
        await pilot.click("#updates-check")
        await pilot.pause()
        detail = _text(app.query_one("#updates-detail", Static))
        assert "1.5.0 available" in detail
        assert "restart" in detail.lower()
        assert "Update 1.5.0 available" in _text(app.query_one("#hint", Static))


async def test_updates_tab_no_manifest_configured(session_manager: DatabaseSessionManager, monkeypatch) -> None:
    from textual.widgets import Static, TabbedContent

    from trace_core.core.settings import settings

    monkeypatch.setattr(settings, "update_manifest", None)
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("5")
        await pilot.pause()
        assert app.query_one(TabbedContent).active == "updates"
        await pilot.click("#updates-check")
        await pilot.pause()
        assert "TRACE_UPDATE_MANIFEST" in _text(app.query_one("#updates-detail", Static))

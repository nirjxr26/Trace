import pytest
from rich.text import Text

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.app import TraceApp

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def _text(widget) -> str:  # type: ignore[no-untyped-def]
    renderable = widget.render()
    return renderable.plain if isinstance(renderable, Text) else str(renderable)


async def _press_until(pilot, app, key: str, needle: str) -> None:
    """Check runs in a worker now, so wait for the worker to land."""
    from textual.widgets import Static

    for _ in range(30):
        await pilot.press(key)
        for _ in range(10):
            await pilot.pause()
            if needle in _text(app.query_one("#settings-detail", Static)):
                return
    assert needle in _text(app.query_one("#settings-detail", Static))


async def _goto_settings_updates(pilot, app) -> None:  # type: ignore[no-untyped-def]
    """Single source for tab switching. Retries key press; pilot focus timing flakes under load."""
    from textual.widgets import Static, TabbedContent

    for _ in range(10):
        await pilot.press("4")
        await pilot.pause()
        if app.query_one(TabbedContent).active == "settings":
            break
    assert app.query_one(TabbedContent).active == "settings"
    # Sections open on Database; move once to Updates and wait for its detail.
    from textual.widgets import ListView

    app.query_one("#settings-sections", ListView).focus()
    for _ in range(5):
        detail = _text(app.query_one("#settings-detail", Static))
        if "Current version" in detail:
            return
        await pilot.press("down")
        await pilot.pause()
    assert "Current version" in _text(app.query_one("#settings-detail", Static))


async def test_updates_tab_check_and_hint(session_manager: DatabaseSessionManager, signed_release, monkeypatch) -> None:
    from textual.widgets import Static

    from trace_core.core.settings import settings

    _, manifest_path, _, _ = signed_release()
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        await _press_until(pilot, app, "c", "1.5.0")
        detail = _text(app.query_one("#settings-detail", Static))
        assert "restart" in detail.lower()
        assert "Update 1.5.0 available" in _text(app.query_one("#hint", Static))


async def test_updates_card_shows_version_block(
    session_manager: DatabaseSessionManager, signed_release, monkeypatch
) -> None:
    from textual.widgets import Button, Static

    from trace_core.core.settings import settings
    from trace_core.tui.app import TraceApp

    _, manifest_path, _, _ = signed_release()
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        detail = _text(app.query_one("#settings-detail", Static))
        assert "Current version" in detail
        await _press_until(pilot, app, "c", "Press u")
        detail = _text(app.query_one("#settings-detail", Static))
        assert "Press u or pick Update below to install." in detail
        assert app.query_one("#update-apply", Button) is not None


async def test_updates_install_guarded_without_update(session_manager: DatabaseSessionManager) -> None:
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.settings import SettingsView

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        view = app.query_one(SettingsView)
        view.run_command("updates-install")
        await pilot.pause()


async def test_install_panel_animates_only_past_the_delay(session_manager: DatabaseSessionManager) -> None:
    """A long step must animate; a step under the delay must hold still.

    The panel used to redraw only when the worker reported progress, so a stage that emits
    nothing — verifying, installing, the health check — sat on one glyph for its whole run.
    """
    from time import monotonic

    from textual.widgets import Static

    from trace_core.tui.screens.settings import SettingsView
    from trace_core.updates.stages import SPIN_DELAY_SECONDS, SPIN_FRAMES, Stage, StageStatus

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        view = app.query_one(SettingsView)
        view._prev, view._current = "0.2.11", "0.2.12"
        view._installing = True
        view._install_state = {s: StageStatus.PENDING for s in Stage}
        view._on_update_stage(Stage.DOWNLOAD, StageStatus.ACTIVE)
        view._dl_total = 0
        await pilot.pause()

        detail = app.query_one("#settings-detail", Static)
        inside = _text(detail)
        assert f"{SPIN_FRAMES[0]} Downloading" in inside
        assert view._spin == 0

        view._active_since = monotonic() - SPIN_DELAY_SECONDS - 0.01
        for _ in range(5):
            view._tick_spin()
            await pilot.pause()
        moved = _text(detail)
        assert view._spin >= 1
        assert f"{SPIN_FRAMES[0]} Downloading" not in moved
        assert any(f"{frame} Downloading" in moved for frame in SPIN_FRAMES)

        view._stop_spin()
        view._installing = False


async def test_updates_tab_no_manifest_configured(session_manager: DatabaseSessionManager, monkeypatch) -> None:

    from trace_core.core.settings import settings

    monkeypatch.setattr(settings, "update_manifest", None)
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        await _press_until(pilot, app, "c", "TRACE_UPDATE_MANIFEST")

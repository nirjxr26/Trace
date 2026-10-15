import inspect

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
    from textual.widgets import Static

    from trace_core.core.settings import settings
    from trace_core.tui.app import TraceApp

    _, manifest_path, _, _ = signed_release()
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        detail = _text(app.query_one("#settings-detail", Static))
        assert "Current version" in detail
        await _press_until(pilot, app, "c", "trace update install --yes")
        detail = _text(app.query_one("#settings-detail", Static))
        assert "Update available with version: v1.5.0" in detail
        assert "trace update install --yes" in detail
        assert not app.query("#update-apply"), "the update affordance is the CLI command, not a button"


async def test_updates_install_guarded_without_update(session_manager: DatabaseSessionManager) -> None:
    """The TUI no longer installs; it must point at the standalone CLI command instead."""
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.settings import SettingsView

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        view = app.query_one(SettingsView)
        view.run_command("updates-install")
        await pilot.pause()

        assert not view.query("UpdateProgressModal")
        assert not hasattr(view, "_progress"), "the TUI must not open an update popup"
        assert not hasattr(view, "action_install"), "the TUI must not install updates"


async def test_check_spinner_animates_then_clears(session_manager: DatabaseSessionManager) -> None:
    """The check spinner must animate on its own timer and stop once the check ends.

    It used to be a static step_line glyph painted into the detail pane, so it never moved.
    """
    from trace_core.tui.screens.settings import SettingsView
    from trace_core.tui.widgets import ThothSpinner

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        view = app.query_one(SettingsView)
        spin = app.query_one("#update-check-spin", ThothSpinner)

        view._checking = True
        view._render_detail()
        await pilot.pause(0.15)
        assert spin.display, "the spinner must show while a check runs"
        assert "Checking for updates" in _text(spin)

        seen = set()
        for _ in range(12):
            await pilot.pause(0.09)
            seen.add(_text(spin)[0])
        assert len(seen) > 1, "the spinner glyph must advance on its own timer"

        view._checking = False
        view._render_detail()
        await pilot.pause()
        assert not spin.display, "the spinner must disappear once the check ends"


async def test_tui_offers_no_install_gesture(session_manager: DatabaseSessionManager) -> None:
    """Installing happens only in the standalone CLI, so no TUI affordance may remain."""
    from textual.binding import Binding

    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens import settings as settings_src
    from trace_core.tui.screens.settings import SettingsView
    from trace_core.tui.widgets import ThothSpinner

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        view = app.query_one(SettingsView)
        keys = [b.key if isinstance(b, Binding) else b[0] for b in SettingsView.BINDINGS]
        assert "u" not in keys, "the install key must be gone from the updates tab"
        assert not hasattr(view, "action_install")
        assert not hasattr(view, "_install_worker")
        assert not app.query("UpdateProgressModal")

    source = inspect.getsource(settings_src)
    assert "TRACE_TUI_DEMO_UPDATE" not in source
    assert ThothSpinner.__module__.endswith("widgets")


async def test_updates_tab_no_manifest_configured(session_manager: DatabaseSessionManager, monkeypatch) -> None:

    from trace_core.core.settings import settings

    monkeypatch.setattr(settings, "update_manifest", None)
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        await _press_until(pilot, app, "c", "TRACE_UPDATE_MANIFEST")


async def test_integrity_verify_runs_once_per_ledger_head(session_manager, monkeypatch) -> None:
    """Highlighting Integrity must not re-scan the ledger while its head stands still."""
    from textual.widgets import ListView, Static

    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    CaseService(session_manager).create_case(CaseCreateDto(title="T", description="d", lead_examiner="Dana"))

    real_verify = AuditService.verify
    calls = 0

    def counting(self):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_verify(self)

    monkeypatch.setattr(AuditService, "verify", counting)

    async def _show_integrity(pilot, app) -> None:  # type: ignore[no-untyped-def]
        for _ in range(10):
            if "Chain Status" in _text(app.query_one("#settings-detail", Static)):
                return
            await pilot.press("down")
            await pilot.pause()
        assert "Chain Status" in _text(app.query_one("#settings-detail", Static))

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        assert calls == 0
        await _show_integrity(pilot, app)
        assert calls == 1
        app.query_one("#settings-sections", ListView).focus()
        await pilot.press("up")
        await pilot.pause()
        await _show_integrity(pilot, app)
        assert calls == 1, f"re-verified an unchanged ledger: {calls} scans"
        CaseService(session_manager).create_case(CaseCreateDto(title="U", description="d", lead_examiner="Dana"))
        app.query_one("#settings-sections", ListView).focus()
        await pilot.press("up")
        await pilot.pause()
        await _show_integrity(pilot, app)
        assert calls == 2, f"stale result shown after the ledger moved: {calls} scans"


async def test_db_snapshot_fetch_runs_once_per_visit(session_manager, monkeypatch) -> None:
    """Database and Diagnostics paint the same snapshot; wiggling sections must not
    re-snapshot, but returning to the tab must."""
    from textual.widgets import ListView, Static

    from trace_core.core.database import health as health_mod

    real_snapshot = health_mod.fetch_db_snapshot
    calls = 0

    def counting(manager=None):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_snapshot(manager)

    monkeypatch.setattr(health_mod, "fetch_db_snapshot", counting)

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await _goto_settings_updates(pilot, app)
        app.query_one("#settings-sections", ListView).focus()
        for _ in range(8):
            await pilot.press("down")
            await pilot.pause()
        base = calls
        assert base >= 1
        for _ in range(8):
            await pilot.press("up")
            await pilot.pause()
        assert calls == base, f"re-snapshotted on section wiggle: {calls} vs {base}"
        assert "Online" in _text(app.query_one("#settings-detail", Static))
        from trace_core.tui.screens.settings import SettingsView

        for _ in range(10):
            if app.query_one(SettingsView)._selected_section() == "Database":
                break
            await pilot.press("up")
            await pilot.pause()
        assert app.query_one(SettingsView)._selected_section() == "Database"
        app.query_one(SettingsView).refresh_data()
        await pilot.pause()
        assert calls == base + 1, f"refresh did not renew the snapshot: {calls} vs {base}"
        app.query_one(SettingsView)._render_detail()
        await pilot.pause()
        assert calls == base + 1, f"repaint re-snapshotted: {calls} vs {base}"
        assert "Migration complete" in _text(app.query_one("#settings-detail", Static))

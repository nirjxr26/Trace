import pytest
from rich.text import Text
from textual.widgets import ListView, Static

from trace_core.audit.dto import AuditEventDto, VerifyResultDto
from trace_core.core.database.health import DbSnapshot
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.app import TraceApp
from trace_core.tui.status import StatusModal

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def _text(widget) -> str:  # type: ignore[no-untyped-def]
    renderable = widget.render()
    return renderable.plain if isinstance(renderable, Text) else str(renderable)


async def _wait(pilot, app, selector: str, needle: str) -> str:  # type: ignore[no-untyped-def]
    for _ in range(30):
        await pilot.pause()
        text = _text(app.screen.query_one(selector, Static))
        if needle in text:
            return text
    return _text(app.screen.query_one(selector, Static))


async def test_palette_command_opens_status_popup(session_manager: DatabaseSessionManager) -> None:
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app._palette_done("app-status")
        await pilot.pause()
        assert isinstance(app.screen, StatusModal)
        ids = [child.id for child in app.screen.query_one("#palette-list", ListView).children]
        assert ids == ["row-database", "row-updates", "row-system", "row-integrity"]


async def test_system_status_row_and_detail(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.widgets import ListView

    monkeypatch.setattr(
        "trace_core.tui.status.health_rows",
        lambda manager: (True, [("Database", "Connected", True), ("Migrations", "up to date", True)]),
    )
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app._palette_done("app-status")
        await pilot.pause()
        view = app.screen.query_one("#palette-list", ListView)
        view.index = 2
        await pilot.press("enter")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StatusModal)
        assert "Settings" in _text(modal.query_one("#status-title", Static))
        text = await _wait(pilot, app, "#status-detail", "PASS")
        assert "FAIL" not in text
        assert "Database" not in text


async def test_database_and_integrity_statuses(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.audit.service import AuditService
    from trace_core.core.database import health

    monkeypatch.setattr(
        health,
        "fetch_db_snapshot",
        lambda manager=None: DbSnapshot(True, "Database connection successful", "sqlite:///**", [], [], []),
    )
    monkeypatch.setattr(
        AuditService,
        "verify",
        lambda self, on_progress=None: VerifyResultDto(events_verified=10, first_seq=1, last_seq=10, is_valid=True),
    )
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app._palette_done("app-status")
        await pilot.pause()
        assert "Connected" in await _wait(pilot, app, "#row-database .cmd-value", "Connected")
        assert "Valid" in await _wait(pilot, app, "#row-integrity .cmd-value", "Valid")


async def test_database_failure_shows_reason(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.core.database import health

    monkeypatch.setattr(
        health,
        "fetch_db_snapshot",
        lambda manager=None: DbSnapshot(False, "Database unreachable", "sqlite:///**", [], [], []),
    )
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app._palette_done("app-status")
        await pilot.pause()
        text = await _wait(pilot, app, "#row-database .cmd-value", "Unreachable")
        assert "Database unreachable" in text


async def test_integrity_mismatch_names_the_event(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.audit.domain import AuditAction
    from trace_core.audit.service import AuditService
    from trace_core.core.clock import now_utc

    result = VerifyResultDto(
        events_verified=2,
        first_seq=1,
        last_seq=2,
        is_valid=False,
        first_mismatch_seq=2,
        mismatch_type="chain_hash",
    )
    event = AuditEventDto(
        seq=2,
        ts=now_utc(),
        action=AuditAction.CASE_UPDATED,
        actor="examiner@host",
        subject_type="case",
        subject_case_number="2026-CR-0001",
        payload_json="{}",
        payload_hash="a" * 64,
        prev_chain="b" * 64,
        chain_hash="c" * 64,
    )
    monkeypatch.setattr(AuditService, "verify", lambda self, on_progress=None: result)
    monkeypatch.setattr(AuditService, "get_by_seq", lambda self, seq: event)
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app._palette_done("app-status")
        await pilot.pause()
        text = await _wait(pilot, app, "#row-integrity .cmd-value", "Mismatch")
        assert "seq 2" in text
        assert "Update" not in text


async def test_updates_row_opens_detail_popup(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.updates import checker

    monkeypatch.setattr(checker, "peek_cached_update", lambda: {"target": "1.5.0"})
    monkeypatch.setattr(checker, "cached_check", lambda target, channel="stable": {"target": "1.5.0"})
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app._palette_done("app-status")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StatusModal)
        view = modal.query_one("#palette-list", ListView)
        view.index = 1
        await pilot.press("enter")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StatusModal)
        assert "Settings" in _text(modal.query_one("#status-title", Static))
        text = await _wait(pilot, app, "#status-detail", "Update available to")
        assert "Update available to 1.5.0" in text
        assert "trace update install" in text


async def test_updates_popup_reports_no_update(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.updates import checker

    monkeypatch.setattr(checker, "cached_check", lambda target, channel="stable": {"target": ""})
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app._palette_done("app-status")
        await pilot.pause()
        app.screen.query_one("#palette-list", ListView).index = 1
        await pilot.press("enter")
        await pilot.pause()
        text = await _wait(pilot, app, "#status-detail", "System is up to date")
        assert "Update not available" in text

"""Audit list projection, sequence search, and keyset paging contracts."""

import json
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import pytest
from sqlalchemy import event as sa_event
from textual.widgets import DataTable
from typer.testing import CliRunner

from trace_core.audit.domain import AuditAction
from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.repository import SqlAlchemyAuditRepository
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.cli.main import app
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.app import TraceApp
from trace_core.tui.screens.audit import PAGE_ROWS

pytestmark = pytest.mark.unit
runner = CliRunner()


def _seed(session_manager: DatabaseSessionManager, count: int, actor: str = "Agent Mulder") -> list[int]:
    seqs: list[int] = []
    with session_manager.session() as s:
        repo = SqlAlchemyAuditRepository(s)
        for i in range(count):
            seq = repo.append(AuditAction.CASE_UPDATED, actor, None, None, {"i": i}, subject_type="case").seq
            seqs.append(seq)
        s.commit()
    return seqs


@contextmanager
def _selects(session_manager: DatabaseSessionManager) -> Generator[list[str], None, None]:
    seen: list[str] = []

    def handler(conn, cursor, sql, params, context, executemany) -> None:  # noqa: ANN001
        flat = " ".join(sql.split())
        if params:
            for value in list(params) if isinstance(params, (list, tuple)) else [params]:
                flat = flat.replace("?", repr(value), 1)
        if "audit_events" in flat:
            seen.append(flat)

    sa_event.listen(session_manager.engine, "before_cursor_execute", handler)
    try:
        yield seen
    finally:
        sa_event.remove(session_manager.engine, "before_cursor_execute", handler)


def test_numeric_search_returns_the_event_with_that_sequence(session_manager: DatabaseSessionManager) -> None:
    seqs = _seed(session_manager, 12)
    target = seqs[4]
    found = AuditService(session_manager).list_event_summaries(AuditFilterDto(search=str(target), limit=50))
    assert [e.seq for e in found] == [target]
    assert AuditService(session_manager).get_by_seq(target) is not None


def test_numeric_search_filters_on_the_primary_key_alone(session_manager: DatabaseSessionManager) -> None:
    seqs = _seed(session_manager, 12)
    with _selects(session_manager) as seen:
        AuditService(session_manager).list_event_summaries(AuditFilterDto(search=str(seqs[4])))
    where = seen[0].split(" WHERE ", 1)[1]
    assert "seq = " in where
    assert "actor" not in where
    assert "action" not in where


def test_text_search_still_matches_substrings(session_manager: DatabaseSessionManager) -> None:
    _seed(session_manager, 3, actor="agent7")
    _seed(session_manager, 3, actor="someone")
    svc = AuditService(session_manager)
    assert len(svc.list_event_summaries(AuditFilterDto(search="agent"))) == 3
    assert len(svc.list_event_summaries(AuditFilterDto(search="gENT7"))) == 3
    assert len(svc.list_event_summaries(AuditFilterDto(search="nobody"))) == 0


def test_summary_list_selects_only_the_light_columns(session_manager: DatabaseSessionManager) -> None:
    _seed(session_manager, 5)
    with _selects(session_manager) as seen:
        AuditService(session_manager).list_event_summaries(AuditFilterDto(limit=5))
    sql = seen[0]
    assert "payload_json" not in sql
    assert "chain_hash" not in sql
    assert "signature" not in sql
    assert "audit_events.actor" in sql
    assert "audit_events.ts" in sql


def test_full_list_still_hydrates_the_whole_ledger_row(session_manager: DatabaseSessionManager) -> None:
    _seed(session_manager, 3)
    events = AuditService(session_manager).list_events(AuditFilterDto(limit=3))
    assert all(e.payload_json and e.chain_hash and e.subject_type for e in events)


def test_keyset_pages_cover_the_whole_ledger_once(session_manager: DatabaseSessionManager) -> None:
    seqs = _seed(session_manager, 23)
    svc = AuditService(session_manager)
    seen: list[int] = []
    before: int | None = None
    pages = 0
    while True:
        page = svc.list_event_summaries(AuditFilterDto(limit=7, before_seq=before))
        if not page:
            break
        pages += 1
        seen.extend(e.seq for e in page)
        before = page[-1].seq
    assert seen == sorted(seqs, reverse=True)
    assert len(seen) == len(set(seen))
    assert pages == 4


def test_keyset_page_equals_the_matching_offset_window(session_manager: DatabaseSessionManager) -> None:
    seqs = _seed(session_manager, 20)
    svc = AuditService(session_manager)
    descending = sorted(seqs, reverse=True)
    by_offset = svc.list_event_summaries(AuditFilterDto(limit=5, offset=5))
    by_keyset = svc.list_event_summaries(AuditFilterDto(limit=5, before_seq=descending[4]))
    assert [e.seq for e in by_offset] == [e.seq for e in by_keyset] == descending[5:10]


def test_keyset_cursor_narrows_the_primary_key_range(session_manager: DatabaseSessionManager) -> None:
    seqs = _seed(session_manager, 20)
    with _selects(session_manager) as seen:
        AuditService(session_manager).list_event_summaries(AuditFilterDto(limit=5, before_seq=sorted(seqs)[9]))
    assert "seq < " in seen[0]


def test_keyset_and_filters_compose(session_manager: DatabaseSessionManager) -> None:
    _seed(session_manager, 6, actor="alice")
    _seed(session_manager, 6, actor="bob")
    svc = AuditService(session_manager)
    page = svc.list_event_summaries(AuditFilterDto(actor="alice", limit=3, before_seq=10**9))
    assert [e.actor for e in page] == ["alice"] * 3
    assert page[-1].seq < 10**9


def test_sequence_filter_returns_exactly_one_event(session_manager: DatabaseSessionManager) -> None:
    seqs = _seed(session_manager, 6)
    svc = AuditService(session_manager)
    assert [e.seq for e in svc.list_event_summaries(AuditFilterDto(before_seq=seqs[3]))] == [
        seqs[2],
        seqs[1],
        seqs[0],
    ]


def test_cli_hint_names_the_next_offset(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 5)
    res = runner.invoke(app, ["audit", "show", "--limit", "2"])
    assert res.exit_code == 0
    assert "More events: audit show --offset 2" in res.stdout


def test_cli_hint_uses_the_keyset_cursor_when_given(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    seqs = _seed(session_manager, 5)
    descending = sorted(seqs, reverse=True)
    res = runner.invoke(app, ["audit", "show", "--limit", "2", "--before-seq", str(descending[0] + 1)])
    assert res.exit_code == 0
    assert f"More events: audit show --before-seq {descending[1]}" in res.stdout


def test_cli_hint_is_absent_on_a_partial_page(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 3)
    res = runner.invoke(app, ["audit", "show", "--limit", "50"])
    assert res.exit_code == 0
    assert "More events" not in res.stdout


def test_cli_numeric_search_finds_the_event(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    seqs = _seed(session_manager, 6, actor="agent7")
    res = runner.invoke(app, ["audit", "show", "--search", str(seqs[3])])
    assert res.exit_code == 0
    assert "1 events" in res.stdout
    missing = runner.invoke(app, ["audit", "show", "--search", "999999"])
    assert "No audit events found" in missing.stdout


def test_json_output_keeps_full_ledger_fidelity(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 3)
    res = runner.invoke(app, ["audit", "show", "--output", "json", "--limit", "3"])
    assert res.exit_code == 0
    rows = json.loads(res.stdout)
    assert len(rows) == 3
    for row in rows:
        assert {"seq", "payload_json", "payload_hash", "chain_hash", "prev_chain"} <= set(row)


def test_case_timeline_still_renders_payload_details(session_manager: DatabaseSessionManager, monkeypatch) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    case = CaseService(session_manager).create_case(CaseCreateDto(title="PayloadProof", lead_examiner="Ex"))
    res = runner.invoke(app, ["audit", "show", "--case", case.number])
    assert res.exit_code == 0
    assert "Title: PayloadProof" in res.stdout


def _script_pager(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    seen: list[str] = []

    def choice() -> str:
        seen.append(answers[len(seen)])
        return answers[len(seen) - 1]

    monkeypatch.setattr("trace_core.core.cli.args.interactive_terminal", lambda: True)
    monkeypatch.setattr("trace_core.audit.helpers._page_choice", choice)
    return seen


def _pages_in(stdout: str) -> list[list[str]]:
    return [page.split() for page in stdout.split("Audit Ledger")[1:]]


def test_pager_walks_older_and_steps_back(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 10)
    _script_pager(monkeypatch, ["enter", "enter", "b", "q"])
    with _selects(session_manager) as seen:
        res = runner.invoke(app, ["audit", "show", "--limit", "3"])
    assert res.exit_code == 0
    assert res.stdout.count("Audit Ledger") == 4
    cursors: list[str | None] = []
    for sql in seen:
        if "seq < " in sql:
            cursors.append(sql.split("seq < ")[1].split()[0])
        else:
            cursors.append(None)
    assert cursors == [None, "8", "5", "8"]


def test_pager_stops_without_a_phantom_final_page(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 9)
    _script_pager(monkeypatch, ["enter", "enter", "enter", "q"])
    res = runner.invoke(app, ["audit", "show", "--limit", "3"])
    assert res.exit_code == 0
    assert res.stdout.count("Audit Ledger") == 3
    assert "No audit events found" not in res.stdout


def test_pager_quits_on_the_first_prompt_without_loading_a_second_page(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 9)
    seen = _script_pager(monkeypatch, ["q"])
    res = runner.invoke(app, ["audit", "show", "--limit", "3"])
    assert res.exit_code == 0
    assert res.stdout.count("Audit Ledger") == 1
    assert len(seen) == 1


def test_pager_back_at_the_newest_page_does_not_loop(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 9)
    _script_pager(monkeypatch, ["b", "b", "b", "q"])
    res = runner.invoke(app, ["audit", "show", "--limit", "3"])
    assert res.exit_code == 0
    assert res.stdout.count("Audit Ledger") == 1


def test_pager_is_inert_when_stdout_is_not_a_terminal(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 9)
    monkeypatch.setattr("trace_core.core.cli.args.interactive_terminal", lambda: False)
    res = runner.invoke(app, ["audit", "show", "--limit", "3"])
    assert res.exit_code == 0
    assert res.stdout.count("Audit Ledger") == 1
    assert "More events: audit show --offset 3" in res.stdout


def test_pager_pages_are_distinct_windows(session_manager: DatabaseSessionManager, monkeypatch) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    seqs = sorted(_seed(session_manager, 9), reverse=True)
    _script_pager(monkeypatch, ["enter", "enter", "q"])
    res = runner.invoke(app, ["audit", "show", "--limit", "3"])
    assert res.exit_code == 0
    pages = AuditService(session_manager)
    assert [e.seq for e in pages.list_event_summaries(AuditFilterDto(limit=3))] == seqs[:3]
    assert [e.seq for e in pages.list_event_summaries(AuditFilterDto(limit=3, before_seq=seqs[2]))] == seqs[3:6]
    assert [e.seq for e in pages.list_event_summaries(AuditFilterDto(limit=3, before_seq=seqs[5]))] == seqs[6:9]


@asynccontextmanager
async def _audit_tab_on_a_long_ledger(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[Any, DataTable, list[int]], None]:
    """Run the audit tab over a ledger longer than one window, with the first window loaded.

    Single source for the prologue every TUI paging test repeats: point the global manager
    at the test database, seed past `PAGE_ROWS` so there is a second page to fetch, mount
    the app, and select the audit tab.
    """
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    seqs = _seed(session_manager, PAGE_ROWS + 25)
    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        table = app.query_one("#audit-table", DataTable)
        assert table.row_count == PAGE_ROWS
        yield pilot, table, seqs


@pytest.mark.unit
@pytest.mark.anyio
async def test_audit_view_pages_back_through_every_event(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _audit_tab_on_a_long_ledger(session_manager, monkeypatch) as (pilot, table, seqs):
        table.focus()
        await pilot.pause()
        with _selects(session_manager) as seen:
            table.move_cursor(row=table.row_count - 1)
            await pilot.pause()
            assert table.row_count == len(seqs)
            keyset = [s for s in seen if "payload_json" not in s and "seq < " in s]
            assert len(keyset) == 1
            detail = [s for s in seen if "payload_json" in s]
            assert len(detail) == 1

            for _ in range(5):
                await pilot.press("down")
            await pilot.pause()
            assert table.row_count == len(seqs)
            assert len([s for s in seen if "seq < " in s]) == 1
            assert len([s for s in seen if "payload_json" in s]) == 6


def test_after_seq_returns_the_events_newer_than_the_cursor(session_manager: DatabaseSessionManager) -> None:
    seqs = _seed(session_manager, 20)
    svc = AuditService(session_manager)
    newer = svc.list_event_summaries(AuditFilterDto(limit=3, after_seq=sorted(seqs)[16]))
    assert [e.seq for e in newer] == sorted(seqs, reverse=True)[:3]
    assert svc.list_event_summaries(AuditFilterDto(after_seq=max(seqs))) == []


def test_keyset_and_after_seq_bracket_the_cursor(session_manager: DatabaseSessionManager) -> None:
    seqs = _seed(session_manager, 9)
    svc = AuditService(session_manager)
    older = svc.list_event_summaries(AuditFilterDto(before_seq=5))
    newer = svc.list_event_summaries(AuditFilterDto(after_seq=5))
    assert [e.seq for e in older] == [4, 3, 2, 1]
    assert [e.seq for e in newer] == [9, 8, 7, 6]
    assert sorted(seqs) == sorted([e.seq for e in older] + [5] + [e.seq for e in newer])


def test_cli_after_seq_pages_upward(session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 9)
    res = runner.invoke(app, ["audit", "show", "--limit", "3", "--after-seq", "5"])
    assert res.exit_code == 0
    assert res.stdout.count("Audit Ledger") == 1
    assert "More events: audit show --offset 3" in res.stdout


@pytest.mark.unit
@pytest.mark.anyio
async def test_audit_header_count_tracks_every_loaded_row(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.widgets import Static

    from trace_core.tui.screens.audit import AUDIT_HEADER_ID

    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    seqs = _seed(session_manager, PAGE_ROWS + 25)
    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        header = str(app.query_one(f"#{AUDIT_HEADER_ID}", Static).render())
        assert header.rstrip().endswith(f"· {PAGE_ROWS}")
        table = app.query_one("#audit-table", DataTable)
        table.scroll_to(y=table.max_scroll_y, animate=False)
        await pilot.pause()
        assert table.row_count == len(seqs)
        header = str(app.query_one(f"#{AUDIT_HEADER_ID}", Static).render())
        assert header.rstrip().endswith(f"· {len(seqs)}")


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("size", [(60, 20), (110, 40), (200, 60)])
async def test_audit_table_stays_inside_the_sidebar(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch, size: tuple[int, int]
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 60)
    app = TraceApp(session_manager)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        table = app.query_one("#audit-table", DataTable)
        left = app.query_one("#audit-left")
        assert table.region.bottom <= left.region.bottom
        assert table.region.right <= left.region.right
        assert table.region.width > 0
        assert table.region.height > 0


@pytest.mark.unit
@pytest.mark.anyio
async def test_audit_view_extends_when_the_viewport_is_scrolled_not_the_cursor(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _audit_tab_on_a_long_ledger(session_manager, monkeypatch) as (pilot, table, seqs):
        cursor_before = table.cursor_row
        with _selects(session_manager) as seen:
            table.scroll_to(y=table.max_scroll_y, animate=False)
            await pilot.pause()
            assert table.row_count == len(seqs)
            assert table.cursor_row == cursor_before
            assert len([s for s in seen if "seq < " in s]) == 1
        assert table.vertical_scrollbar.position == table.scroll_offset.y


@pytest.mark.unit
@pytest.mark.anyio
async def test_audit_view_detail_is_not_refetched_when_the_tab_is_revisited(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    _seed(session_manager, 5)
    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        with _selects(session_manager) as seen:
            for _ in range(2):
                await pilot.press("4")
                await pilot.pause()
                await pilot.press("3")
                await pilot.pause()
            assert app.query_one("#audit-table", DataTable).row_count == 5
            assert len([s for s in seen if "payload_json" in s]) == 0
            assert len([s for s in seen if "payload_json" not in s]) == 2

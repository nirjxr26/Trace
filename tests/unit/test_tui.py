"""Pilot tests for the fullscreen console: mount, navigate, dossier, verify, db."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import DataTable

from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.app import TraceApp

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


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
        assert "2026-CR-0001" in shot
        assert "2026-CR-0002" in shot
        assert "Status" in shot
        assert "─" in shot

        await pilot.press("down")
        await pilot.pause()
        assert "Alpha" in _text(app.query_one("#case-dossier", Static))

        await pilot.press("3")
        await pilot.pause()
        assert app.query_one(TabbedContent).active == "audit"
        audit_table = app.query_one("#audit-table", DataTable)
        assert audit_table.row_count == 3
        assert len(audit_table.columns) == 2
        audit_rows = [str(cell) for i in range(audit_table.row_count) for cell in audit_table.get_row_at(i)]
        assert any("Case Updated" in cell for cell in audit_rows), audit_rows
        assert "Case details updated" in _text(app.query_one("#audit-detail", Static))
        assert "Seq" in app.export_screenshot()

        await pilot.press("4")
        await pilot.pause()
        assert app.query_one(TabbedContent).active == "settings"
        from textual.widgets import ListView, Static

        sections = app.query_one("#settings-sections", ListView)
        assert len(list(sections.children)) == 5
        labels = [_text(item.query_one(Static)) for item in sections.children]
        assert sum(label.endswith("Storage & Paths") for label in labels) == 1, labels
        assert "Database" in _text(app.query_one("#settings-detail", Static))
        assert "Online" in _text(app.query_one("#settings-detail", Static))

        await pilot.press("down")
        await pilot.pause()
        detail = _text(app.query_one("#settings-detail", Static))
        assert "Current version" in detail

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
            # No constructor argument: the modal reaches the app through `self.app`, and
            # passing one bound it to the Screen's `name` parameter instead. Production opens
            # it the same way, at `app.py:152`.
            PaletteModal(),
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


@pytest.mark.anyio
async def test_the_device_summary_and_header_carry_no_separating_rule(session_manager) -> None:
    """One divider fewer: the count now sits in the table header, not on its own line."""
    from trace_core.tui.app import TraceApp

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.pause()
        left = app.screen.query_one("#device-left")
        kinds = [type(w).__name__ for w in left.children]

        assert kinds[:3] == ["Input", "Static", "Static"], (
            f"summary and header must be adjacent with no divider between them: {kinds}"
        )
        from textual.widgets import Static

        summary = app.screen.query_one("#device-summary", Static)
        assert "kind: " in str(summary.content)
        assert str(summary.styles.text_align) == "start", (
            "the kind is a label for the list below it, so it shares the header's column"
        )
        header = app.screen.query_one("#device-header", Static)
        assert summary.region.x == header.region.x, f"kind at x={summary.region.x} but header at x={header.region.x}"
        assert summary.size.height == 1, f"the kind is one caption line, not a band: {summary.size}"
        search = app.screen.query_one("#device-search")
        assert summary.region.y == search.region.y + search.region.height + 1, (
            f"one blank row above the kind: search ends "
            f"{search.region.y + search.region.height}, kind at {summary.region.y}"
        )
        header = app.screen.query_one("#device-header", Static)
        assert header.region.y == summary.region.y + 2, (
            f"and one blank row below it, so it is not top-heavy: "
            f"kind at {summary.region.y}, header at {header.region.y}"
        )


@pytest.mark.anyio
async def test_the_audit_sidebar_search_has_no_divider_below_it(session_manager) -> None:
    from trace_core.tui.app import TraceApp

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.pause()
        kinds = [type(w).__name__ for w in app.screen.query_one("#audit-left").children]
        assert kinds[:3] == ["Input", "Static", "Static"], f"the search box must not be followed by a rule: {kinds}"


def _painted_columns(strips: list, rows: range) -> dict:  # type: ignore[no-untyped-def]
    """First character column of each needle within the left panel, per row."""
    found: dict = {}
    for y in rows:
        text = strips[y].text[:42]
        for needle in ("Search node or model", "kind: all", "Device"):
            index = text.find(needle)
            if index >= 0:
                found[needle] = index
    return found


@pytest.mark.anyio
async def test_every_left_panel_label_shares_one_column(session_manager, device_file_env) -> None:
    """The search box, the kind, the table header and the rows must not each pick their
    own left edge. Measured from painted cells, not from stylesheet declarations, so a
    rule that parses but does not land cannot pass."""
    from trace_core.devices.helpers import do_inspect
    from trace_core.tui.app import TraceApp

    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.pause()
        strips = app.screen._compositor.render_strips()
        left = app.screen.query_one("#device-left")
        rows = range(left.region.y, left.region.y + left.region.height)
        columns = _painted_columns(strips, rows)

        assert "Search node or model" in columns, f"search placeholder not painted: {columns}"
        assert "kind: all" in columns, f"kind not painted: {columns}"
        assert "Device" in columns, f"header not painted: {columns}"
        assert columns["kind: all"] == columns["Device"], f"the kind must sit on the header's column: {columns}"

        row_line = next(strips[y].text[:42] for y in rows if "disk-a.dd" in strips[y].text[:42])
        assert row_line.find("disk-a.dd") == columns["Search node or model"], (
            f"search text must sit on the row text column: "
            f"search {columns['Search node or model']}, row {row_line.find('disk-a.dd')}"
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("key", "table_id"),
    [("1", "case-table"), ("2", "device-table"), ("3", "audit-table")],
)
async def test_no_left_sidebar_shows_a_scrollbar(session_manager, device_file_env, key, table_id) -> None:
    """The left columns are short lists inside a bordered panel; a scrollbar there eats a
    column the model name needs. Asserted on the rendered scrollbar width, and with
    content that genuinely overflows, so a rule that only works when nothing scrolls
    cannot pass."""
    from trace_core.devices.helpers import do_inspect
    from trace_core.tui.app import TraceApp

    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press(key)
        await pilot.pause()
        await pilot.pause()
        table = app.screen.query_one(f"#{table_id}")

        assert table.vertical_scrollbar.outer_size.width == 0, (
            f"{table_id} shows a vertical scrollbar: {table.vertical_scrollbar.outer_size.width} cells wide"
        )
        assert table.horizontal_scrollbar.outer_size.height == 0, f"{table_id} shows a horizontal scrollbar"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("key", "pane_id"),
    [("1", "cases-right"), ("2", "device-right"), ("3", "audit-right")],
)
async def test_no_dossier_shows_a_scrollbar(session_manager, device_file_env, key, pane_id) -> None:  # type: ignore[no-untyped-def]
    """The dossier panes keep scrolling but lose the chrome, like the tables before
    them. Asserted with content that genuinely overflows, so a rule that only works
    when nothing scrolls cannot pass."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices.helpers import do_inspect
    from trace_core.tui.app import TraceApp

    CaseService(session_manager).create_case(CaseCreateDto(title="Dossier", lead_examiner="Ex"))
    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))

    app = TraceApp(session_manager)
    async with app.run_test(size=(60, 16)) as pilot:
        await pilot.press(key)
        await pilot.pause()
        await pilot.pause()
        pane = app.screen.query_one(f"#{pane_id}")
        assert pane.show_vertical_scrollbar, f"{pane_id} has nothing to scroll in this setup"
        assert pane.max_scroll_y > 0, f"{pane_id} is not scrollable in this setup"
        assert pane.vertical_scrollbar.outer_size.width == 0, f"{pane_id} shows a vertical scrollbar"
        assert pane.horizontal_scrollbar.outer_size.height == 0, f"{pane_id} shows a horizontal scrollbar"


@pytest.mark.anyio
async def test_settings_headers_share_row_and_spacing(session_manager) -> None:
    """The Settings title, its divider, and the section list must sit on the same rows as
    the detail title, its divider, and the body. The left title carried a 1-row top pad
    nothing on the right had, so every row below it drifted. Measured from painted
    cells, so a rule that parses but does not land cannot pass."""
    from trace_core.tui.app import TraceApp

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.pause()
        strips = app.screen._compositor.render_strips()
        left = app.screen.query_one("#settings-left")
        content = left.content_region
        rows = range(content.y, content.y + 12)

        def row_with(needle: str, lo: int, hi: int) -> int:
            for y in rows:
                if needle in strips[y].text[lo:hi]:
                    return y
            raise AssertionError(f"{needle!r} not painted in cols {lo}-{hi}")

        assert row_with("Settings", 0, 40) == row_with("Database", 40, 120), (
            "the Settings and detail titles must share a row"
        )
        assert row_with("────", 0, 40) == row_with("────", 40, 120), (
            "the Settings rule and the detail divider must share a row"
        )
        list_row = row_with("\u203a Database", 0, 40)
        body_row = row_with("Online", 40, 120)
        assert list_row == body_row, (
            f"section list (row {list_row}) and detail body (row {body_row}) must start together"
        )


@pytest.mark.anyio
async def test_hidden_spinner_does_no_render_work(session_manager, monkeypatch) -> None:
    """The update spinner ticked at 12.5 fps forever, Rich-rendering while invisible."""
    from trace_core.tui import widgets as widgets_mod
    from trace_core.tui.app import TraceApp
    from trace_core.tui.widgets import ThothSpinner

    calls = 0
    real_parts = widgets_mod._thoth_parts

    def counting(renderable):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_parts(renderable)

    monkeypatch.setattr(widgets_mod, "_thoth_parts", counting)

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        spin = ThothSpinner("Checking")
        await app.mount(spin)
        await pilot.pause()
        assert calls > 0, "a visible spinner must still animate"
        spin.display = False
        await pilot.pause()
        calls = 0
        spin.tick()
        spin.tick()
        assert calls == 0, f"hidden spinner did render work: {calls} renders"
        await spin.remove()
        assert spin._tick_timer is None, "unmounted spinner left its timer running"


@pytest.mark.anyio
async def test_unchanged_refresh_patches_without_clearing(session_manager, monkeypatch) -> None:
    """A refresh that changes nothing must not clear the table - the empty flash and
    cursor jump replayed on every poll, tab switch, and keystroke-pause."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.cases import CasesView

    numbers = [
        CaseService(session_manager)
        .create_case(CaseCreateDto(title=title, description="d", lead_examiner="Dana"))
        .number
        for title in ("One", "Two")
    ]

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.pause()
        table = app.screen.query_one("#case-table", DataTable)
        real_clear = table.clear
        clears = 0

        def counting(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal clears
            clears += 1
            return real_clear(*args, **kwargs)

        monkeypatch.setattr(table, "clear", counting)
        await pilot.press("down")
        await pilot.pause()
        assert table.cursor_row == 1
        app.query_one(CasesView).refresh_data()
        await pilot.pause()
        assert clears == 0, "unchanged refresh cleared the table"
        assert table.cursor_row == 1, "unchanged refresh moved the cursor"
        assert table.row_count == 2
        CaseService(session_manager).close_case(numbers[0], reason="done", closed_by="Dana")
        app.query_one(CasesView).refresh_data()
        await pilot.pause()
        assert clears == 0, "same-keys refresh cleared the table"
        assert "CLOSED" in str(table.get_row_at(1)), "in-place patch did not update content"


@pytest.mark.anyio
async def test_background_tabs_skip_mount_fetch(session_manager, monkeypatch) -> None:
    """Mounting must not fetch for tabs the operator has not opened. The activation
    refresh covers first paint, so a mount-time fetch elsewhere is pure waste -
    including a full ledger verify on the settings tab."""
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens import audit as audit_mod
    from trace_core.tui.screens import cases as cases_mod
    from trace_core.tui.screens import devices as devices_mod
    from trace_core.tui.screens.settings import SettingsView

    counts: dict[str, int] = {}
    for mod, cls_name in (
        (cases_mod, "CasesView"),
        (devices_mod, "DevicesView"),
        (audit_mod, "AuditView"),
    ):
        cls = getattr(mod, cls_name)
        real = cls.refresh_data

        def counting(self, _real=real, _name=cls_name):  # type: ignore[no-untyped-def]
            counts[_name] = counts.get(_name, 0) + 1
            return _real(self)

        monkeypatch.setattr(cls, "refresh_data", counting)
    real_settings = SettingsView.refresh_data

    def counting_settings(self):  # type: ignore[no-untyped-def]
        counts["SettingsView"] = counts.get("SettingsView", 0) + 1
        return real_settings(self)

    monkeypatch.setattr(SettingsView, "refresh_data", counting_settings)

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert counts.get("DevicesView", 0) == 0, f"devices fetched before visit: {counts}"
        assert counts.get("AuditView", 0) == 0, f"audit fetched before visit: {counts}"
        assert counts.get("SettingsView", 0) == 0, f"settings fetched before visit: {counts}"
        assert counts.get("CasesView", 0) >= 1, "initial tab never fetched"
        for key in ("2", "3", "4"):
            await pilot.press(key)
            await pilot.pause()
            await pilot.pause()
        assert counts.get("DevicesView", 0) >= 1, "devices tab blank after visit"
        assert counts.get("AuditView", 0) >= 1, "audit tab blank after visit"
        assert counts.get("SettingsView", 0) >= 1, "settings tab blank after visit"


@asynccontextmanager
async def _refused_case_delete_app(
    seeded_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[Any, Pilot, list[tuple[str, dict]]], None]:
    from trace_core.cases.service import CaseService
    from trace_core.tui.screens.cases import CasesView

    app = TraceApp(seeded_manager)
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        view = app.query_one(CasesView)
        monkeypatch.setattr(CaseService, "delete_case", lambda self, *args, **kwargs: False)
        notices: list[tuple[str, dict]] = []
        monkeypatch.setattr(app, "notify", lambda message, **kwargs: notices.append((message, kwargs)))
        yield view, pilot, notices


async def test_a_refused_archive_reports_failure_instead_of_success(
    seeded_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _refused_case_delete_app(seeded_manager, monkeypatch) as (view, pilot, notices):
        view._archived("2026-CR-0001")
        await pilot.pause()

    assert any(kw.get("severity") == "error" and "does not exist" in msg for msg, kw in notices), notices
    assert not any("archived." in msg for msg, _ in notices), notices


async def test_a_refused_purge_reports_failure_instead_of_success(
    seeded_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _refused_case_delete_app(seeded_manager, monkeypatch) as (view, pilot, notices):
        view._purged("2026-CR-0001")
        await pilot.pause()

    assert any(kw.get("severity") == "error" and "does not exist" in msg for msg, kw in notices), notices
    assert not any("purged." in msg for msg, _ in notices), notices


async def test_review_moves_and_returns_the_case(seeded_manager: DatabaseSessionManager) -> None:
    from trace_core.cases.domain import CaseStatus
    from trace_core.cases.service import CaseService
    from trace_core.tui.screens.cases import CasesView

    app = TraceApp(seeded_manager)
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        view = app.query_one(CasesView)
        view._reviewed("2026-CR-0001", False)
        await pilot.pause()
        assert CaseService(seeded_manager).get_case("2026-CR-0001").status is CaseStatus.UNDER_REVIEW

        view._reviewed("2026-CR-0001", True)
        await pilot.pause()
        assert CaseService(seeded_manager).get_case("2026-CR-0001").status is CaseStatus.OPEN


@asynccontextmanager
async def _audit_tab_with_one_event(
    session_manager: DatabaseSessionManager,
) -> AsyncGenerator[tuple[TraceApp, Pilot], None]:
    from trace_core.audit.domain import AuditAction
    from trace_core.audit.repository import SqlAlchemyAuditRepository

    with session_manager.session() as session:
        SqlAlchemyAuditRepository(session).append(
            AuditAction.CASE_CREATED, "Ex", "2026-CR-0001", None, {}, subject_type="case"
        )
        session.commit()

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 32)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        yield app, pilot


async def _audit_detail(app: TraceApp, pilot: Pilot) -> str:
    from textual.widgets import Static

    from trace_core.tui.screens.audit import AuditView

    app.query_one(AuditView).render_detail()
    await pilot.pause()
    return _text(app.query_one("#audit-detail", Static))


async def test_the_audit_pane_marks_an_unreadable_payload(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _audit_tab_with_one_event(session_manager) as (app, pilot):
        monkeypatch.setattr("trace_core.tui.screens.audit.parse_details", lambda payload: None)
        detail = await _audit_detail(app, pilot)

    assert "unreadable — details cannot be shown" in detail, detail


def test_the_palette_and_keys_offer_only_what_the_tui_runs() -> None:
    from trace_core.tui.palette import COMMANDS, KeysModal

    names = {entry[0] for entry in COMMANDS}
    assert {"updates-check", "audit-anchor", "database-migrate"} <= names
    assert not {"updates-install", "uninstall"} & names, "the TUI installs and uninstalls only through the CLI"
    advertised = " ".join(f"{key} {description}" for _, items in KeysModal.GROUPS for key, description in items)
    assert "install update" not in advertised


def test_the_header_count_stays_within_the_table_width() -> None:
    from trace_core.tui.theme import header_with_count

    columns = (("Device", 15), ("Size", 9))
    span = 1 + sum(width for _, width in columns) + 2 * (len(columns) - 1)
    for count in (1, 12, 100, 999):
        line = header_with_count(columns, count)
        assert line.endswith(f"· {count}")
        assert len(line) <= span, f"count {count} pushed the header past the table's own width: {line!r}"


async def test_the_anchor_command_verifies_a_file_and_reports_the_verdict(
    seeded_manager: DatabaseSessionManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.widgets import Input

    from trace_core.audit.service import AuditService
    from trace_core.audit.signing import sign_bytes
    from trace_core.core.canonical import canonical_json
    from trace_core.tui.screens.audit import AuditView

    svc = AuditService(seeded_manager)
    seq, chain = svc.head()
    envelope = {"last_seq": seq, "last_chain": chain}
    key_id, signature = sign_bytes(canonical_json(envelope))
    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({**envelope, "key_id": key_id, "signature": signature}), encoding="utf-8")

    app = TraceApp(seeded_manager)
    notices: list[tuple[str, dict]] = []
    async with app.run_test(size=(120, 32)) as pilot:
        monkeypatch.setattr(app, "notify", lambda message, **kwargs: notices.append((message, kwargs)))
        await pilot.press("3")
        await pilot.pause()
        app.query_one(AuditView).run_command("audit-anchor")
        await pilot.pause()
        app.screen.query_one("#text-input", Input).value = str(anchor)
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if notices:
                break

    assert notices, "the anchor check must report a verdict"
    assert "tail matches" in notices[0][0], notices
    assert notices[0][1].get("severity") != "error", notices


async def test_repaint_selection_does_not_swallow_unexpected_failures(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.widgets import DataTable

    from trace_core.tui.widgets import repaint_selection

    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 30)):
        table: DataTable = DataTable()
        table.add_column("A")
        table.add_row("one")

        def _boom(self: DataTable, coordinate: object, value: object, **kwargs: object) -> None:
            raise RuntimeError("bug")

        monkeypatch.setattr(DataTable, "update_cell_at", _boom)
        with pytest.raises(RuntimeError, match="bug"):
            repaint_selection(table, None, 0, lambda index, selected: ["x"])


async def test_repaint_selection_skips_a_stale_coordinate(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.coordinate import Coordinate
    from textual.widgets import DataTable

    from trace_core.tui.widgets import repaint_selection

    attempted: list[Coordinate] = []
    original = DataTable.update_cell_at

    def _record(self: DataTable, coordinate: Coordinate, value: object, *, update_width: bool = False) -> None:
        attempted.append(coordinate)
        original(self, coordinate, value, update_width=update_width)

    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 30)):
        table: DataTable = DataTable()
        table.add_column("A")
        table.add_row("one")
        monkeypatch.setattr(DataTable, "update_cell_at", _record)
        repaint_selection(table, None, 0, lambda index, selected: ["two", "three"])
        assert table.get_cell_at(Coordinate(0, 0)) == "two"
        assert [coordinate.column for coordinate in attempted] == [0]


async def test_the_cases_dossier_self_check_heading_is_not_a_ledger_verdict(
    seeded_manager: DatabaseSessionManager,
) -> None:
    from textual.widgets import Static

    app = TraceApp(seeded_manager)
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        dossier = _text(app.query_one("#case-dossier", Static))

    assert "SELF-CHECK" in dossier, dossier
    assert "INTEGRITY" not in dossier, dossier


async def test_the_audit_detail_self_check_heading_matches_the_row_scope(
    session_manager: DatabaseSessionManager,
) -> None:
    async with _audit_tab_with_one_event(session_manager) as (app, pilot):
        detail = await _audit_detail(app, pilot)

    assert "SELF-CHECK" in detail, detail
    assert "INTEGRITY" not in detail, detail

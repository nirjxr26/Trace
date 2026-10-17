"""TUI tribunal: the devices tab mounts, filters, gates, and never grants real-hardware access."""

from pathlib import Path

import pytest
from rich.text import Text
from textual.widgets import DataTable, Input, Static

from trace_core.tui.app import TraceApp

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def _table(app: TraceApp) -> DataTable:
    return app.query_one("#device-table", DataTable)


def _rows(app: TraceApp) -> list[list[str]]:

    table = app.query_one("#device-table", DataTable)
    return [[str(cell) for cell in table.get_row_at(index)] for index in range(table.row_count)]


def _text(widget) -> str:  # type: ignore[no-untyped-def]
    from rich.text import Text

    renderable = widget.render()
    return renderable.plain if isinstance(renderable, Text) else str(renderable)


def _detail(app: TraceApp) -> str:

    return _text(app.query_one("#device-detail", Static))


def _summary(app: TraceApp) -> str:

    return _text(app.query_one("#device-summary", Static))


async def _wait_detail(app: TraceApp, pilot, needle: str, tries: int = 40) -> str:  # type: ignore[no-untyped-def]
    """Poll the detail pane until the action's effect lands, or fail on the last render."""
    for _ in range(tries):
        await pilot.pause()
        try:
            renderable = app.query_one("#device-detail", Static).render()
            rendered = renderable.plain if isinstance(renderable, Text) else str(renderable)
            if needle in rendered:
                return rendered
        except Exception:
            continue
    return _detail(app)


async def test_the_devices_tab_mounts(session_manager, device_file_env: Path) -> None:
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        assert _table(app).row_count == 2
        assert any("disk-a.dd" in cell for row in _rows(app) for cell in row)


async def test_the_devices_tab_is_in_the_tab_order() -> None:
    from trace_core.tui.app import _TAB_ORDER

    assert "devices" in _TAB_ORDER
    assert _TAB_ORDER[0] == "cases"


async def test_the_devices_hint_is_declared() -> None:
    from trace_core.tui.app import TAB_HINTS

    assert "devices" in TAB_HINTS
    assert "Inspect" in TAB_HINTS["devices"]
    assert "Check" in TAB_HINTS["devices"]


async def test_search_filters_the_device_table(session_manager, device_file_env: Path) -> None:
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        app.query_one("#device-search", Input).value = "disk-b"
        await pilot.pause(0.8)
        assert _table(app).row_count == 1
        assert any("disk-b.dd" in cell for row in _rows(app) for cell in row)
        assert "disk-a.dd" not in " ".join(cell for row in _rows(app) for cell in row)


async def test_kind_cycles_and_filters(session_manager, device_file_env: Path) -> None:
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()
        assert "kind: file" in _summary(app)
        await pilot.press("k")
        await pilot.pause()
        assert "kind: os" in _summary(app)
        assert _table(app).row_count == 0


async def test_check_records_a_gate_and_shows_it(session_manager, device_file_env: Path) -> None:
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("c")
        detail = await _wait_detail(app, pilot, "READ_ONLY")
        assert "WRITE PROTECTION" in detail
        assert "open_exclusive" in detail


async def test_check_writes_the_gate_to_the_ledger(session_manager, device_file_env: Path) -> None:
    from sqlalchemy import text

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("c")
        await _wait_detail(app, pilot, "Kind")
    with session_manager.session() as session:
        actions = [row[0] for row in session.execute(text("SELECT action FROM audit_events")).fetchall()]
    assert "DEVICE_GATE_CHECKED" in actions


async def test_inspect_records_the_device_identity(session_manager, device_file_env: Path) -> None:
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("i")
        detail = await _wait_detail(app, pilot, "IDENTITY")
        assert "Hardware" in detail
        assert "Serial" in detail
        assert "SYNTH-" in detail
        assert "Interface" in detail
        assert "Source" in detail


def test_the_left_table_shows_only_name_and_size() -> None:
    from trace_core.devices.domain import DeviceKind
    from trace_core.devices.dto import DeviceInfoDto
    from trace_core.tui.screens.devices import TABLE_COLUMNS, _display_name

    assert [label for label, _ in TABLE_COLUMNS] == ["Device", "Size"]
    file_like = DeviceInfoDto(node="/tmp/disk-a.dd", kind=DeviceKind.FILE, requires_real_hardware_opt_in=False)
    assert _display_name(file_like) == "disk-a.dd"
    named = DeviceInfoDto(
        node=r"\\.\PhysicalDrive1",
        kind=DeviceKind.OS,
        requires_real_hardware_opt_in=True,
        model_hint="Seagate Expansion",
    )
    assert _display_name(named) == "Seagate Expansion"
    bare = DeviceInfoDto(node=r"\\.\PhysicalDrive1", kind=DeviceKind.OS, requires_real_hardware_opt_in=True)
    assert _display_name(bare) == "Drive 1"


def test_the_device_name_is_readable_not_a_raw_device_path() -> None:
    """`\\\\.\\PhysicalDrive0` is a Win32 device path, not something an operator reads."""
    from trace_core.devices.domain import DeviceKind
    from trace_core.devices.dto import DeviceInfoDto
    from trace_core.tui.screens.devices import _display_name

    def name(node: str) -> str:
        return _display_name(DeviceInfoDto(node=node, kind=DeviceKind.OS, requires_real_hardware_opt_in=True))

    assert name(r"\\.\PhysicalDrive0") == "Drive 0"
    assert name(r"\\.\PhysicalDrive12") == "Drive 12"
    assert name(r"\\.\PHYSICALDRIVE3") == "Drive 3"
    assert name("/dev/sda") == "sda"
    for shown in (name(r"\\.\PhysicalDrive0"), name(r"\\.\PHYSICALDRIVE3")):
        assert "\\" not in shown
        assert "." not in shown


def test_the_device_column_never_overflows_its_width() -> None:
    """A long model hint must not spill past the column into the Size column."""
    from trace_core.devices.domain import DeviceKind
    from trace_core.devices.dto import DeviceInfoDto
    from trace_core.tui.screens.devices import TABLE_COLUMNS, DevicesView

    width = TABLE_COLUMNS[0][1]
    long_name = DeviceInfoDto(
        node="/dev/sda",
        kind=DeviceKind.FILE,
        requires_real_hardware_opt_in=False,
        model_hint="WD My Passport 2TB External USB 3.0",
    )
    view = DevicesView.__new__(DevicesView)
    for selected in (False, True):
        cell = view.row_cells(long_name, selected)[0]
        assert len(cell) <= width, f"name overflowed the column: {cell!r} ({len(cell)} > {width})"

    unwieldy = DeviceInfoDto(
        node="/dev/sdb",
        kind=DeviceKind.FILE,
        requires_real_hardware_opt_in=False,
        model_hint="ACME SuperDrive 9000 XLR Thunderbolt Reference Edition",
    )
    for selected in (False, True):
        cell = view.row_cells(unwieldy, selected)[0]
        assert len(cell) <= width, f"name overflowed the column: {cell!r} ({len(cell)} > {width})"
        assert cell.endswith("…"), "a clamped name must show it was truncated"
        assert len(cell.strip()) > 4, "a clamped name must keep readable content, not collapse to an ellipsis"

    short = DeviceInfoDto(node="/dev/sda", kind=DeviceKind.FILE, requires_real_hardware_opt_in=False, model_hint="sda")
    assert "…" not in view.row_cells(short, False)[0]


def test_the_model_hint_is_normalised_for_display() -> None:
    """Vendors append part numbers and capacity; the label keeps the product name."""
    from trace_core.devices.renderers import readable_model

    assert readable_model("NVMe Micron_2400_MTFDKBA512QFM") == "NVMe Micron"
    assert readable_model("Samsung SSD 990 PRO 2TB") == "Samsung SSD 990 PRO"
    assert readable_model("WD My Passport 2TB External USB 3.0") == "WD My Passport"

    for keep in ("WDC WD10EZEX-08W", "Seagate Expansion", "KINGSTON SA400S37/240G"):
        assert readable_model(keep) == keep, f"a real model name must survive intact: {keep}"


def test_a_single_token_name_is_clamped_not_collapsed() -> None:
    """A path or part number is one long token; it must not vanish into a bare ellipsis."""
    from trace_core.core.ui.renderers import fit_text

    path = r"C:\Users\nirja\AppData\Local\Temp\pytest-of-nirja\disk-a.dd"
    clamped = fit_text(path, 20)
    assert clamped.endswith("…")
    assert len(clamped) == 20
    assert clamped != "…"
    assert clamped.startswith("C:"), "the head of the path must survive"


def test_the_device_title_and_list_use_the_normalised_name() -> None:
    from trace_core.devices.domain import DeviceKind
    from trace_core.devices.dto import DeviceInfoDto
    from trace_core.tui.screens.devices import _display_name

    device = DeviceInfoDto(
        node=r"\\.\PhysicalDrive0",
        model_hint="NVMe Micron_2400_MTFDKBA512QFM",
        kind=DeviceKind.OS,
        requires_real_hardware_opt_in=True,
    )
    assert _display_name(device) == "NVMe Micron"
    assert device.model_hint == "NVMe Micron_2400_MTFDKBA512QFM", "the raw hint must not be mutated"


async def test_the_detail_pane_reads_plainly_and_heads_sections_in_accent(
    session_manager, device_file_env: Path
) -> None:
    """No CLI flag may leak into the GUI, and the section heads must match SELF-CHECK."""
    from textual.widgets import Static

    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.devices import DevicesView

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        view = app.query_one(DevicesView)
        view.refresh_data()
        await pilot.pause()
        if not view._items:
            pytest.skip("no device visible to this adapter")

        _table(app).move_cursor(row=0)
        view.render_detail()
        await pilot.pause()

        plain = _text(app.query_one("#device-detail", Static))
        assert "--allow-real-hardware" not in plain, "a CLI flag must not appear in the GUI"
        assert "Real HW" not in plain, "the terse label is replaced by readable wording"
        assert "Hardware" in plain
        assert any(phrase in plain for phrase in ("access needs confirming", "emulated or image-backed")), (
            "the hardware row must say what it means"
        )
        assert plain.splitlines()[0] != r"\\.\PhysicalDrive0", "the title must be the readable name"
        assert any(line.startswith("Node") for line in plain.splitlines()), "the raw node stays as a labelled row"

        from trace_core.devices.domain import DeviceKind
        from trace_core.devices.dto import DeviceInfoDto

        real = DeviceInfoDto(
            node=r"\\.\PhysicalDrive0",
            model_hint=None,
            kind=DeviceKind.OS,
            requires_real_hardware_opt_in=True,
        )
        view._items = [real]
        _table(app).move_cursor(row=0)
        view.render_detail()
        await pilot.pause()

        gated = _text(app.query_one("#device-detail", Static))
        assert "--allow-real-hardware" not in gated, "a CLI flag must not appear in the GUI"
        assert "access needs confirming" in gated, "real hardware must still be flagged as gated"
        assert gated.splitlines()[0] == "Drive 0", "the title must be the readable name"


async def test_the_identity_section_head_is_drawn_in_the_accent(session_manager, device_file_env: Path) -> None:
    """The section heads must carry the accent token, like SELF-CHECK on the Cases tab."""
    from trace_core.core.ui.theme import THEME_HEX
    from trace_core.tui.app import TraceApp

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("i")
        detail = await _wait_detail(app, pilot, "IDENTITY")

        body = app.query_one("#device-detail", Static)
        want = THEME_HEX["blue"].lstrip("#")
        want_rgb = tuple(int(want[i : i + 2], 16) for i in (0, 2, 4))
        found: set[str] = set()
        for line in body.render_lines(body.size.region):
            text = "".join(seg.text for seg in line).strip()
            if text != "IDENTITY":
                continue
            for seg in line:
                colour = seg.style.color if seg.style is not None else None
                triplet = getattr(colour, "triplet", None) if colour is not None else None
                if triplet == want_rgb:
                    found.add(text)
        assert found, f"IDENTITY head must be drawn in the accent blue {want_rgb}"
        assert detail, "the identity section must render"


async def test_a_synthetic_device_needs_no_opt_in(session_manager, device_file_env: Path, monkeypatch) -> None:
    """[D24]/[D27] a keypress must not imply consent, and a file device needs none."""
    from trace_core.devices import helpers as helpers_module

    granted: list[bool] = []
    real = helpers_module.do_check

    def _spy(_session, node, **kwargs):
        granted.append(bool(kwargs.get("allow_real_hardware")))
        return real(_session, node, **kwargs)

    monkeypatch.setattr("trace_core.devices.helpers.do_check", _spy)

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause(0.8)
    assert granted == [False]


async def test_real_hardware_prompts_before_any_access(session_manager, device_file_env: Path, monkeypatch) -> None:
    from trace_core.devices.domain import DeviceKind
    from trace_core.devices.dto import DeviceInfoDto

    monkeypatch.setenv("TRACE_DEVICE_ADAPTER", "win32")
    monkeypatch.setattr(
        "trace_core.devices.helpers.do_list",
        lambda *_a, **_k: [
            DeviceInfoDto(
                node=r"\\.\PhysicalDrive0",
                kind=DeviceKind.OS,
                requires_real_hardware_opt_in=True,
                size_bytes=1_000_000_000_000,
                model_hint="Real Disk",
            )
        ],
    )
    granted: list[bool] = []
    monkeypatch.setattr(
        "trace_core.devices.helpers.do_check",
        lambda _s, node, **kwargs: granted.append(bool(kwargs.get("allow_real_hardware"))),
    )

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause(0.6)
    assert granted == [], "the service was reached without answering the consent prompt"


async def test_no_adapter_configured_renders_empty_without_crashing(
    session_manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.devices.service import ENV_ADAPTER, ENV_DEVICE_ROOT

    monkeypatch.setenv(ENV_ADAPTER, "file")
    monkeypatch.delenv(ENV_DEVICE_ROOT, raising=False)
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        assert _table(app).row_count == 0


async def test_a_hostile_model_string_reaches_the_terminal_sanitised(
    session_manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[D21] hardware strings are attacker-controlled bytes."""
    from trace_core.devices import synthetic
    from trace_core.devices.service import ENV_ADAPTER, ENV_DEVICE_ROOT

    synthetic.write_disk(tmp_path / "evil.dd", size=64)
    monkeypatch.setenv(ENV_ADAPTER, "file")
    monkeypatch.setenv(ENV_DEVICE_ROOT, str(tmp_path))
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        assert _table(app).row_count == 1
        rendered = _detail(app) + " ".join(cell for row in _rows(app) for cell in row)
        assert "\x1b[" not in rendered, "an escape sequence reached the terminal"


async def test_a_plugged_in_drive_appears_without_any_keypress(session_manager, device_file_env: Path) -> None:
    from trace_core.devices import synthetic
    from trace_core.tui.screens.devices import DevicesView

    synthetic.write_disk(device_file_env / "disk-a.dd", size=2048)
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        (device_file_env / "disk-a.dd").unlink()
        synthetic.write_disk(device_file_env / "disk-c.dd", seed=b"hotplug", size=512)
        view = app.screen.query_one(DevicesView)
        view._poll_devices()
        await pilot.pause()
        names = [cell for row in _rows(app) for cell in row]
        assert any("disk-c.dd" in name for name in names)
        assert not any("disk-a.dd" in name for name in names)


async def test_the_quiet_poll_never_toasts_on_failure(session_manager, device_file_env: Path, monkeypatch) -> None:
    from trace_core.tui.screens.devices import DevicesView

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        assert _table(app).row_count == 2
        monkeypatch.setattr(
            "trace_core.devices.helpers.do_list",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("adapter gone")),
        )
        before = len(app._notifications)
        app.screen.query_one(DevicesView)._poll_devices()
        await pilot.pause()
        assert len(app._notifications) == before
        assert _table(app).row_count == 2


async def test_the_poll_skips_enumeration_while_nothing_changed(
    session_manager, device_file_env: Path, monkeypatch
) -> None:
    from trace_core.tui.screens.devices import DevicesView

    calls: list[int] = []
    real = __import__("trace_core.devices.helpers", fromlist=["do_list"]).do_list

    def _counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("trace_core.devices.helpers.do_list", _counting)
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        mounted_calls = len(calls)
        assert mounted_calls >= 1
        app.screen.query_one(DevicesView)._poll_devices()
        await pilot.pause()
        assert len(calls) == mounted_calls, "an unchanged token must not re-enumerate"


async def test_the_poll_enumerates_as_soon_as_the_token_moves(
    session_manager, device_file_env: Path, monkeypatch
) -> None:
    from trace_core.devices import synthetic
    from trace_core.tui.screens.devices import DevicesView

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        synthetic.write_disk(device_file_env / "disk-hot.dd", seed=b"hot", size=256)
        app.screen.query_one(DevicesView)._poll_devices()
        await pilot.pause()
        assert any("disk-hot.dd" in cell for row in _rows(app) for cell in row)


async def test_denial_reaches_the_toast_unchanged(session_manager, device_file_env: Path, monkeypatch) -> None:
    from trace_core.devices.domain import DeviceAccessDeniedError

    def _denied(*_args, **_kwargs):
        raise DeviceAccessDeniedError("access denied for X")

    monkeypatch.setattr("trace_core.devices.helpers.do_check", _denied)
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        before = len(app._notifications)
        await pilot.press("c")
        await pilot.pause()
        messages = [n.message for n in list(app._notifications)[before:]]
    assert any("access denied for X" in m for m in messages)


async def test_the_device_table_has_no_horizontal_scroller(session_manager, device_file_env: Path) -> None:
    """The table and its header must fit the sidebar with a real row present. This ran
    empty before, so it passed while a single device overflowed both: the DataTable
    scrolled sideways and the header's count clipped off the panel."""
    from textual.widgets import DataTable

    from trace_core.devices.helpers import do_inspect
    from trace_core.tui.screens.devices import TABLE_COLUMNS

    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))

    assert sum(width for _, width in TABLE_COLUMNS) <= 40
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.pause()
        table = app.query_one("#device-table", DataTable)
        assert table.scrollbar_size_horizontal == 0
        assert table.scrollable_content_region.width >= sum(width for _, width in TABLE_COLUMNS)
        assert table.max_scroll_x == 0, (
            f"device table scrolls sideways: virtual={table.virtual_size} region={table.region}"
        )
        header = app.query_one("#device-header", Static)
        full = str(header.content)
        painted = app.screen._compositor.render_strips()[header.region.y].text
        assert full in painted, f"header clipped off the panel: {full!r} not painted"


@pytest.mark.anyio
async def test_a_device_link_event_names_the_device(session_manager, device_file_env) -> None:
    """A DEVICE_LINKED row names the case but not the drive; selecting one showed a link
    with nothing on the other end of it."""
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices.helpers import do_inspect, do_link
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.audit import AUDIT_DETAIL_ID, AuditView

    case = CaseService(session_manager).create_case(CaseCreateDto(title="T", description="d", lead_examiner="Dana"))
    node = str(device_file_env / "disk-a.dd")
    do_inspect(session_manager, node)
    do_link(session_manager, node, case.number, label="bag 4471")

    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(AuditView)
        event = next(
            e
            for e in AuditService(session_manager).list_events(AuditFilterDto(case_number=case.number))
            if e.action.value == "DEVICE_LINKED"
        )
        view._detail = event
        view._detail_seq = event.seq
        view.render_detail()
        await pilot.pause()
        await pilot.pause()
        text = str(getattr(app.screen.query_one(f"#{AUDIT_DETAIL_ID}"), "content", ""))

    assert "Device Linked" in text, "the detail must carry its own Device Linked section"
    # The heading names the model and its capacity, not the OS handle - the same rule the
    # case dossier uses. The synthetic disk's model is its own filename.
    assert "disk-a.dd" in text, "the linked device must be named by its model"
    assert "2.0 KB" in text, "and its size shown"
    assert "bag 4471" in text, "and its label carried through"


async def test_device_history_names_the_recorder(session_manager, device_file_env: Path) -> None:
    """Regression: the HISTORY block read row.case_number, which ObservationDto never had,
    so device-history crashed on any inspected device. Observations carry the recorder,
    not a case - linkage is current-state in case_devices, not a property of old rows."""
    from trace_core.devices.helpers import do_history, do_inspect
    from trace_core.tui.screens.devices import DevicesView

    node = str(device_file_env / "disk-a.dd")
    serial = do_inspect(session_manager, node).fingerprint.serial
    recorder = do_history(session_manager, serial)[0].inspected_by

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.pause()
        app.query_one(DevicesView).run_command("history")
        await pilot.pause()
        text = _detail(app)

    assert "HISTORY \u00b7" in text, f"history block did not render: {text!r}"
    assert recorder in text, f"recorder {recorder!r} missing from history: {text!r}"


async def test_audit_dividers_refit_after_a_width_change(session_manager, device_file_env: Path) -> None:
    """A divider baked for a wide window wraps into a phantom short row when the pane
    narrows. The resize path must rebuild every divider for the live width, leaving no
    short remainder row anywhere in the pane."""
    from textual.events import Resize

    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices.helpers import do_inspect, do_link
    from trace_core.tui.screens.audit import AUDIT_DETAIL_ID, AuditView

    case = CaseService(session_manager).create_case(CaseCreateDto(title="T", description="d", lead_examiner="Dana"))
    node = str(device_file_env / "disk-a.dd")
    do_inspect(session_manager, node)
    do_link(session_manager, node, case.number, label="bag 4471")

    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(AuditView)
        event = next(
            e
            for e in AuditService(session_manager).list_events(AuditFilterDto(case_number=case.number))
            if e.action.value == "DEVICE_LINKED"
        )
        view._detail = event
        view._detail_seq = event.seq
        view.render_detail()
        await pilot.pause()
        pane = app.screen.query_one("#audit-right")
        from rich.text import Text

        stale = Text()
        stale.append("Device Linked\n")
        stale.append("\u2500" * (pane.content_region.width + 20) + "\n")
        app.screen.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(stale)
        await pilot.pause()
        # Simulate what a real narrowing leaves behind: stale content and a width
        # cache from before it moved. Mount already cached the live width, which
        # would - correctly - early-return, so the moved width is seeded by hand.
        view._detail_width = None
        size = app.screen.size
        view.on_resize(Resize(size, size, size))
        await pilot.pause()
        width = pane.content_region.width
        assert view._detail_width == width
        strips = app.screen._compositor.render_strips()
        lengths = set()
        content = pane.content_region
        for y in range(content.y, content.y + content.height):
            line = strips[y].text[pane.content_region.x : pane.content_region.x + width].rstrip()
            if line and set(line) == {"\u2500"}:
                lengths.add(len(line))
        assert lengths, "expected divider rows in the detail pane"
        assert len(lengths) == 1, f"divider rows differ in length - a wrapped remnant is present: {sorted(lengths)}"


async def test_device_poll_pauses_on_hidden_tab(session_manager, monkeypatch) -> None:
    """The 1 Hz change token fired on background tabs too. _token is only ever read by
    the poll tick, so its call count is the poll's footprint."""
    import asyncio

    from trace_core.tui.screens.devices import DevicesView

    real_token = DevicesView._token
    calls = 0

    def counting(self):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_token(self)

    monkeypatch.setattr(DevicesView, "_token", counting)

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.pause()
        await asyncio.sleep(0.3)
        calls = 0
        await asyncio.sleep(1.3)
        assert calls == 0, f"poll ticked while hidden: {calls} token reads"
        await pilot.press("2")
        await pilot.pause()
        calls = 0
        await asyncio.sleep(1.3)
        assert calls > 0, "poll never resumed on the visible tab"


async def test_acknowledge_accepts_an_unverified_source_after_the_typed_token(
    session_manager, device_file_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from trace_core.audit.models import AuditEventModel
    from trace_core.devices import helpers as device_helpers
    from trace_core.devices.file_device import UNKNOWN_PROTECTION, FileDevice
    from trace_core.devices.service import DeviceService

    adapter = FileDevice(device_file_env, behaviour=UNKNOWN_PROTECTION)
    monkeypatch.setattr(
        device_helpers, "_service", lambda manager=None: DeviceService(manager, adapter, adapter, adapter)
    )

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.press(*"UNVERIFIED")
        await pilot.press("enter")
        detail = await _wait_detail(app, pilot, "UNKNOWN")
        assert "WRITE PROTECTION" in detail

    with session_manager.session() as session:
        actions = [row.action for row in session.scalars(select(AuditEventModel).order_by(AuditEventModel.seq)).all()]
    assert "DEVICE_OVERRIDE" in actions, "the acknowledgement must reach the service and the ledger"


async def test_acknowledge_refuses_any_other_token(
    session_manager, device_file_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.devices import helpers as device_helpers
    from trace_core.devices.file_device import UNKNOWN_PROTECTION, FileDevice
    from trace_core.devices.service import DeviceService
    from trace_core.tui.screens.devices import DevicesView

    adapter = FileDevice(device_file_env, behaviour=UNKNOWN_PROTECTION)
    monkeypatch.setattr(
        device_helpers, "_service", lambda manager=None: DeviceService(manager, adapter, adapter, adapter)
    )

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        view = app.query_one(DevicesView)
        await pilot.press("a")
        await pilot.pause()
        await pilot.press(*"YES")
        await pilot.press("enter")
        await pilot.pause()
        assert view._gate is None, "an inexact token must not run the gate"
        assert "WRITE PROTECTION" not in _detail(app)
        assert any("UNVERIFIED" in note.message for note in app._notifications)

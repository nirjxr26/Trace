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


async def test_inspect_records_a_fingerprint(session_manager, device_file_env: Path) -> None:
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("i")
        detail = await _wait_detail(app, pilot, "FINGERPRINT")
        assert "Real HW" in detail
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
    assert _display_name(bare) == "PhysicalDrive1"


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
    from textual.widgets import DataTable

    from trace_core.tui.screens.devices import TABLE_COLUMNS

    assert sum(width for _, width in TABLE_COLUMNS) <= 40
    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        table = app.query_one("#device-table", DataTable)
        assert table.scrollbar_size_horizontal == 0
        assert table.scrollable_content_region.width >= sum(width for _, width in TABLE_COLUMNS)

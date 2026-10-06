"""Tribunal tests for the Windows adapter: index parsing, fail-closed probe, D33 shape."""

import json
import pathlib

import pytest

from trace_core.devices import file_device, linux, synthetic, win32
from trace_core.devices._subprocess import HelperFailure
from trace_core.devices.domain import DeviceGoneError, DeviceInfo, DeviceKind, UnknownCause, WpVerdict

pytestmark = pytest.mark.unit


def _node(index: int) -> str:
    return rf"\\.\PhysicalDrive{index}"


def _info(index: int = 0) -> DeviceInfo:
    return DeviceInfo(
        node=_node(index),
        kind=DeviceKind.OS,
        requires_real_hardware_opt_in=True,
        size_bytes=1000,
        model_hint="Model",
    )


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (r"\\.\PhysicalDrive0", 0),
        (r"\\.\PhysicalDrive12", 12),
        (r"\\.\physicaldrive3", 3),
        ("\\\\.\\PhysicalDrive7", 7),
        (r"\\.\PHYSICALDRIVE4", 4),
        ("PhysicalDrive9", 9),
        (r"\\.\PhysicalDrive", None),
        (r"\\.\PhysicalDriveX", None),
        (r"\\.\PhysicalDrive-1", None),
        ("", None),
        (r"\\.\Volume{abc}", None),
        (r"\\.\PhysicalDrive 1", None),
    ],
)
def test_physical_drive_index_parsing(node: str, expected: int | None) -> None:
    assert win32._index_of(node) is expected


def test_enumerated_drives_are_real_hardware_needing_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        win32.Win32Device,
        "_drive",
        lambda self, index: (
            None if index > 2 else win32._Drive(index, 500, "S1", "M1", "F1", win32.DeviceInterface.SATA)
        ),
    )
    devices = win32.Win32Device().list_block_devices()
    assert [d.node for d in devices] == [_node(0), _node(1), _node(2)]
    assert all(d.requires_real_hardware_opt_in for d in devices)
    assert devices[0].size_bytes == 500


def test_enumeration_is_empty_when_no_handle_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (None, 2))
    assert win32.Win32Device().list_block_devices() == []


def test_enumeration_never_shells_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """[D23] list is discovery: no smartctl enrichment, only CIM metadata like lsblk."""
    monkeypatch.setattr(
        win32.Win32Device,
        "_drive",
        lambda self, index: None if index > 0 else win32._Drive(0, 10, "S", "M", None, win32.DeviceInterface.USB),
    )
    monkeypatch.setattr(
        win32,
        "run_capped",
        lambda argv, **k: pytest.fail(f"list reached for enrichment: {argv}") if argv[0] == "smartctl" else b"[]",
    )
    assert len(win32.Win32Device().list_block_devices()) == 1


def test_absent_drive_gates_unknown_never_writable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (None, 2))
    gate = win32.Win32Device().verify(_info())
    assert gate.verdict is WpVerdict.UNKNOWN
    assert gate.evidence.unknown_cause is UnknownCause.DEVICE_DISAPPEARED
    assert gate.evidence.platform == "windows"


def test_unparseable_node_gates_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = win32.Win32Device().verify(_info())
    gate = win32.Win32Device().verify(
        DeviceInfo(node="nonsense", kind=DeviceKind.OS, requires_real_hardware_opt_in=True)
    )
    assert gate.verdict is WpVerdict.UNKNOWN
    assert gate.evidence.unknown_cause is UnknownCause.DEVICE_DISAPPEARED


def test_inspect_of_an_absent_drive_raises_device_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32.Win32Device, "_drive", lambda self, index: None)
    with pytest.raises(DeviceGoneError):
        win32.Win32Device().inspect(_info(5))


def test_inspect_of_an_unparseable_node_raises_device_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DeviceGoneError):
        win32.Win32Device().inspect(DeviceInfo(node="nope", kind=DeviceKind.OS, requires_real_hardware_opt_in=True))


def test_probe_reports_writable_when_the_ioctl_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (7, 0))
    monkeypatch.setattr(win32, "_close", lambda handle: None)
    monkeypatch.setattr(win32, "_is_writable", lambda handle: True)
    gate = win32.Win32Device().verify(_info())
    assert gate.verdict is WpVerdict.WRITABLE
    assert {c.name for c in gate.evidence.checks} >= {win32.CHECK_EXISTENCE, win32.CHECK_IS_WRITABLE}


def test_no_dead_constant_survives_in_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    import ast
    import re

    batch = "\n".join(p.read_text(encoding="utf-8") for p in pathlib.Path("src/trace_core/devices").glob("*.py"))
    tests = "\n".join(p.read_text(encoding="utf-8") for p in pathlib.Path("tests/unit").glob("test_devices*.py"))
    dead: list[str] = []
    for path in pathlib.Path("src/trace_core/devices").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        ast.parse(text)
        for const in re.findall(r"^([A-Z][A-Z0-9_]{3,})\s*[:=]", text, re.M):
            if len(re.findall(rf"\b{const}\b", text)) <= 1 and not re.search(rf"\b{const}\b", batch + tests):
                dead.append(f"{path.name}:{const}")
    assert not dead, f"unused module constants: {dead}"


def test_an_unsupported_ioctl_is_unknown_not_a_false_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off-platform the ioctl cannot answer; claiming access denied would misstate why."""
    monkeypatch.setattr(win32, "_try_open", lambda node: (7, 0))
    monkeypatch.setattr(win32, "_close", lambda handle: None)
    monkeypatch.setattr(win32, "_is_writable", lambda handle: None)
    gate = win32.Win32Device().verify(_info())
    assert gate.verdict is WpVerdict.UNKNOWN
    assert gate.evidence.unknown_cause is UnknownCause.IOCTL_FAILURE
    assert any(c.result == "unsupported" for c in gate.evidence.checks)


def test_is_writable_reports_none_when_there_is_no_kernel32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_windll", lambda: None)
    assert win32._is_writable(5) is None
    assert win32._try_open(r"\\.\PhysicalDrive0") == (None, 0)


def test_access_denied_names_eacces_with_elevation_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (7, 0))
    monkeypatch.setattr(win32, "_close", lambda handle: None)
    monkeypatch.setattr(win32, "_is_writable", lambda handle: win32.ERROR_ACCESS_DENIED)
    gate = win32.Win32Device().verify(_info())
    assert gate.verdict is WpVerdict.UNKNOWN
    assert gate.evidence.unknown_cause is UnknownCause.EACCES
    assert "elevated" in " ".join(c.detail or "" for c in gate.evidence.checks)


def test_an_ioctl_failure_is_never_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (7, 0))
    monkeypatch.setattr(win32, "_close", lambda handle: None)
    monkeypatch.setattr(win32, "_is_writable", lambda handle: 1117)
    gate = win32.Win32Device().verify(_info())
    assert gate.verdict is WpVerdict.UNKNOWN
    assert gate.evidence.unknown_cause is UnknownCause.IOCTL_FAILURE


def test_the_probe_closes_its_handle_on_every_path(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[int] = []
    monkeypatch.setattr(win32, "_try_open", lambda node: (42, 0))
    monkeypatch.setattr(win32, "_close", closed.append)
    monkeypatch.setattr(win32, "_is_writable", lambda handle: True)
    win32.Win32Device().verify(_info())
    assert closed == [42]

    closed.clear()
    monkeypatch.setattr(win32, "_is_writable", lambda handle: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        win32.Win32Device().verify(_info())
    assert closed == [42]


def test_inspect_closes_its_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[int] = []
    monkeypatch.setattr(win32, "_try_open", lambda node: (9, 0))
    monkeypatch.setattr(win32, "_close", closed.append)
    monkeypatch.setattr(win32, "_geometry_size", lambda handle: 77)
    monkeypatch.setattr(win32, "_query_text", lambda handle, key: f"{key}-val")
    monkeypatch.setattr(win32, "_interface", lambda handle: win32.DeviceInterface.NVME)
    inspection = win32.Win32Device().inspect(_info())
    assert closed == [9]
    assert inspection.fingerprint.capacity_bytes == 77
    assert inspection.fingerprint.firmware == "firmware-val"
    assert inspection.fingerprint.interface is win32.DeviceInterface.NVME


def test_smartctl_type_comes_only_from_a_closed_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """[D20] the `-d` value is never built from serial or model bytes."""
    adapter = win32.Win32Device()
    monkeypatch.setattr(win32, "smartctl_readiness", lambda: None)
    seen: list[list[str]] = []
    monkeypatch.setattr(
        win32,
        "run_capped",
        lambda argv, **k: seen.append(argv) or json.dumps({"smartctl": {"exit_status": 0}, "wwn": {"naa": 1}}).encode(),
    )
    for interface, expected in (
        (win32.DeviceInterface.USB, "usb"),
        (win32.DeviceInterface.SATA, "sat"),
        (win32.DeviceInterface.NVME, "nvme"),
        (win32.DeviceInterface.SCSI, "scsi"),
    ):
        adapter._enrich(0, interface)
        assert seen[-1][2] == expected

    monkeypatch.setattr(
        win32, "run_capped", lambda argv, **k: pytest.fail(f"unmapped interface reached smartctl: {argv}")
    )
    assert adapter._enrich(0, win32.DeviceInterface.UNKNOWN) == (None, None)


@pytest.mark.parametrize(
    ("cause", "payload"),
    [
        (UnknownCause.SMARTCTL_TIMEOUT, None),
        (UnknownCause.TOOL_MISSING, None),
        (UnknownCause.SMARTCTL_MALFORMED, b"{not json"),
        (UnknownCause.SMARTCTL_MALFORMED, b"[]"),
    ],
)
def test_enrichment_degrades_to_native_with_a_named_cause(
    monkeypatch: pytest.MonkeyPatch, cause: UnknownCause, payload: bytes | None
) -> None:
    monkeypatch.setattr(win32, "smartctl_readiness", lambda: None)
    if payload is None:

        def _fail(argv, **k):
            raise HelperFailure(cause, "nope")

        monkeypatch.setattr(win32, "run_capped", _fail)
    else:
        monkeypatch.setattr(win32, "run_capped", lambda argv, **k: payload)
    assert win32.Win32Device()._enrich(0, win32.DeviceInterface.SATA)[0] is cause


def test_smartctl_device_type_never_reaches_the_node_unvalidated(monkeypatch: pytest.MonkeyPatch) -> None:
    """[D20], [D21] the node is an argv element, never interpolated into a shell string."""
    monkeypatch.setattr(win32, "smartctl_readiness", lambda: None)
    seen: list[list[str]] = []
    monkeypatch.setattr(
        win32,
        "run_capped",
        lambda argv, **k: seen.append(argv) or json.dumps({"smartctl": {"exit_status": 0}}).encode(),
    )
    win32.Win32Device()._enrich(3, win32.DeviceInterface.SATA)
    assert seen[0][-1] == r"\\.\PhysicalDrive3"
    assert all(isinstance(part, str) for part in seen[0])


def test_evidence_shape_is_identical_across_all_three_adapters(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """[D33] the fake, Linux and Windows probes emit structurally identical evidence."""
    fake = file_device.FileDevice(tmp_path)
    synthetic.write_disk(tmp_path / "d.dd", size=128)
    fake_devices = fake.list_block_devices()
    fake_gate = fake.verify(fake_devices[0])

    lin = linux.LinuxDevice()
    monkeypatch.setattr(lin, "_exists", lambda name: True)
    monkeypatch.setattr(lin, "_exclusive_open", lambda path: True)
    monkeypatch.setattr(linux, "read_sysfs_ro", lambda name: True)
    monkeypatch.setattr(lin, "_blkroget", lambda path: True)
    linux_gate = lin.verify(
        DeviceInfo(node="/dev/sda", kind=DeviceKind.OS, requires_real_hardware_opt_in=True, size_bytes=128)
    )

    monkeypatch.setattr(win32, "_try_open", lambda node: (5, 0))
    monkeypatch.setattr(win32, "_close", lambda handle: None)
    monkeypatch.setattr(win32, "_is_writable", lambda handle: True)
    win_gate = win32.Win32Device().verify(_info())

    for gate in (fake_gate, linux_gate, win_gate):
        assert type(gate.verdict) is WpVerdict
        assert gate.evidence.adapter_version
        assert gate.evidence.checks
        assert gate.evidence.checks[0].name == "exists"
        assert all(c.name and c.result for c in gate.evidence.checks)

    assert {g.evidence.platform for g in (fake_gate, linux_gate, win_gate)} == {"fake", "linux", "windows"}
    assert len({type(g.evidence).__name__ for g in (fake_gate, linux_gate, win_gate)}) == 1
    assert {tuple(sorted(vars(c))) for g in (fake_gate, linux_gate, win_gate) for c in g.evidence.checks} == {
        ("detail", "name", "result")
    }, "every probe row must carry exactly name/result/detail"


def test_oversized_hardware_strings_are_bounded_not_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    """[D21] a hostile MODEL string must not survive unbounded into the fingerprint."""
    from trace_core.devices.domain import MAX_DEVICE_STRING

    hostile = "M" * 100_000
    monkeypatch.setattr(win32, "_try_open", lambda node: (3, 0))
    monkeypatch.setattr(win32, "_close", lambda handle: None)
    monkeypatch.setattr(win32, "_geometry_size", lambda handle: 10)
    monkeypatch.setattr(win32, "_query_text", lambda handle, key: hostile if key == "model" else "S")
    monkeypatch.setattr(win32, "_interface", lambda handle: win32.DeviceInterface.USB)
    monkeypatch.setattr(
        win32, "run_capped", lambda argv, **k: (_ for _ in ()).throw(HelperFailure(UnknownCause.TOOL_MISSING, "x"))
    )
    inspection = win32.Win32Device().inspect(_info())
    assert len(inspection.fingerprint.model) <= MAX_DEVICE_STRING


def test_change_token_lists_dos_devices_without_opening_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_query_dos_devices", lambda: {"C:", "PhysicalDrive0"})
    assert win32.Win32Device().change_token() == ("C:", "PhysicalDrive0")


def test_change_token_is_empty_off_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_windll", lambda: None)
    assert win32.Win32Device().change_token() == ()
    assert win32._query_dos_devices() == set()


def test_enumeration_lists_denied_drives_instead_of_hiding_them(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (None, 5))
    monkeypatch.setattr(win32.Win32Device, "_wmi", lambda self: {})
    devices = win32.Win32Device().list_block_devices()
    assert len(devices) == win32.MAX_DRIVES
    assert all(d.requires_real_hardware_opt_in for d in devices)
    assert all(d.size_bytes is None and d.model_hint is None for d in devices)


def test_enumeration_still_skips_genuinely_absent_drives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (None, 2))
    assert win32.Win32Device().list_block_devices() == []


def test_inspect_of_a_denied_drive_names_access_not_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    from trace_core.devices.domain import DeviceAccessDeniedError

    monkeypatch.setattr(win32, "_try_open", lambda node: (None, 5))
    with pytest.raises(DeviceAccessDeniedError, match="[Ee]levat"):
        win32.Win32Device().inspect(_info(0))


def test_probe_of_a_denied_drive_is_eacces_without_opening(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (None, 5))
    monkeypatch.setattr(win32, "_is_writable", lambda handle: pytest.fail("the probe must not open a denied drive"))
    checks, cause = win32.Win32Device()._probe(0)
    assert cause is UnknownCause.EACCES
    assert "elevated" in " ".join(c.detail or "" for c in checks)


def test_wmi_enrichment_names_a_drive_without_opening_it(monkeypatch: pytest.MonkeyPatch) -> None:
    document = [
        {
            "DeviceID": "\\\\.\\PHYSICALDRIVE0",
            "Model": "NVMe Micron_2400",
            "SerialNumber": "ABC123  ",
            "Size": 512105932800,
        },
        {
            "DeviceID": "\\\\.\\PHYSICALDRIVE1",
            "Model": "Seagate Expansion Desk",
            "SerialNumber": "NA8K3P5X",
            "Size": 2000398934016,
        },
    ]
    monkeypatch.setattr(win32, "run_capped", lambda argv, **k: __import__("json").dumps(document).encode())
    enriched = win32.Win32Device()._wmi()
    assert enriched[1]["Model"] == "Seagate Expansion Desk"
    assert enriched[0]["SerialNumber"] == "ABC123  "


def test_wmi_enrichment_accepts_a_single_drive_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        win32, "run_capped", lambda argv, **k: b"{" + b'"DeviceID": "\\\\\\\\.\\\\PHYSICALDRIVE2"' + b"}"
    )
    assert 2 in win32.Win32Device()._wmi()


def test_wmi_enrichment_degrades_to_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from trace_core.devices._subprocess import HelperFailure

    monkeypatch.setattr(
        win32, "run_capped", lambda argv, **k: (_ for _ in ()).throw(HelperFailure(UnknownCause.TOOL_MISSING, "x"))
    )
    assert win32.Win32Device()._wmi() == {}
    monkeypatch.setattr(win32, "run_capped", lambda argv, **k: b"{not json")
    assert win32.Win32Device()._wmi() == {}


def test_wmi_enrichment_is_skipped_off_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32.sys, "platform", "linux")
    monkeypatch.setattr(win32, "run_capped", lambda argv, **k: pytest.fail("no subprocess off-platform"))
    assert win32.Win32Device()._wmi() == {}


def test_a_denied_drive_lists_under_its_real_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (None, 5))
    monkeypatch.setattr(
        win32.Win32Device,
        "_wmi",
        lambda self: {i: {"Model": f"Drive {i}", "SerialNumber": f"S{i}", "Size": 1000 + i} for i in range(64)},
    )
    devices = win32.Win32Device().list_block_devices()
    assert [d.model_hint for d in devices] == [f"Drive {i}" for i in range(64)]
    assert [d.size_bytes for d in devices] == [1000 + i for i in range(64)]


def test_a_denied_drive_without_cim_data_lists_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_try_open", lambda node: (None, 5))
    monkeypatch.setattr(win32.Win32Device, "_wmi", lambda self: {})
    devices = win32.Win32Device().list_block_devices()
    assert len(devices) == win32.MAX_DRIVES
    assert all(d.size_bytes is None and d.model_hint is None for d in devices)


def _descriptor(*, serial=b"S12345", model=b"Samsung SSD 870", firmware=b"FW1", bus=0x11) -> bytes:
    """A minimal STORAGE_DEVICE_DESCRIPTOR. Offsets are byte positions from its start."""
    header = bytearray(40)
    header[16:20] = (40).to_bytes(4, "little")
    header[20:24] = (40 + len(model) + 1).to_bytes(4, "little")
    header[24:28] = (40 + len(model) + 1 + len(firmware) + 1).to_bytes(4, "little")
    header[28] = bus
    return bytes(header) + model + b"\x00" + firmware + b"\x00" + serial + b"\x00"


def test_decode_reads_offsets_not_fixed_positions() -> None:
    raw = _descriptor()
    assert win32._decode(raw, "serial") == "S12345"
    assert win32._decode(raw, "model") == "Samsung SSD 870"
    assert win32._decode(raw, "firmware") == "FW1"


def test_decode_refuses_absent_or_broken_descriptors() -> None:
    assert win32._decode(_descriptor(serial=b""), "serial") is None
    assert win32._decode(b"\x00" * 10, "serial") is None
    assert win32._decode(_descriptor(), "vendor") is None
    broken = bytearray(_descriptor())
    broken[24:28] = (9999).to_bytes(4, "little")
    assert win32._decode(bytes(broken), "serial") is None


def test_query_text_reads_through_the_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes as _ctypes

    raw = _descriptor()
    buffer = _ctypes.create_string_buffer(raw, len(raw))
    query = _ctypes.create_string_buffer(64)
    monkeypatch.setattr(win32, "_property_query", lambda: query)
    monkeypatch.setattr(win32, "_device_ioctl", lambda handle, code, query, in_size, size: (buffer, len(raw)))
    assert win32._query_text(7, "model") == "Samsung SSD 870"
    assert win32._query_text(7, "serial") == "S12345"
    assert win32._query_text(7, "firmware") == "FW1"


def test_property_query_memory_survives_into_the_ioctl(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes as _ctypes

    seen: list[bytes] = []
    query = _ctypes.create_string_buffer(64)

    def _capture(handle, code, addr, in_size, size):
        seen.append(_ctypes.string_at(addr, 8))
        return None

    monkeypatch.setattr(win32, "_property_query", lambda: query)
    monkeypatch.setattr(win32, "_device_ioctl", _capture)
    win32._query_text(7, "model")
    assert seen == [bytes([0, 0, 0, 0, 0, 0, 0, 0])]


@pytest.mark.parametrize(
    ("bus", "expected"),
    [
        (0x11, win32.DeviceInterface.NVME),
        (0x07, win32.DeviceInterface.USB),
        (0x0B, win32.DeviceInterface.SATA),
        (0x01, win32.DeviceInterface.SCSI),
        (0x14, win32.DeviceInterface.VIRTUAL),
        (0x00, win32.DeviceInterface.UNKNOWN),
        (0xFF, win32.DeviceInterface.UNKNOWN),
    ],
)
def test_interface_comes_from_the_bus_type(monkeypatch: pytest.MonkeyPatch, bus: int, expected) -> None:
    import ctypes as _ctypes

    raw = _descriptor(bus=bus)
    buffer = _ctypes.create_string_buffer(raw, len(raw))
    query = _ctypes.create_string_buffer(64)
    monkeypatch.setattr(win32, "_property_query", lambda: query)
    monkeypatch.setattr(win32, "_device_ioctl", lambda handle, code, query, in_size, size: (buffer, len(raw)))
    assert win32._interface(7) is expected


def test_interface_is_unknown_when_the_descriptor_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "_property_query", lambda: None)
    assert win32._interface(7) is win32.DeviceInterface.UNKNOWN


def test_the_property_query_declares_its_input_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """The zero-input-size defect: geometry worked while every property query failed."""
    import ctypes as _ctypes

    raw = _descriptor()
    buffer = _ctypes.create_string_buffer(raw, len(raw))
    seen: list[tuple] = []
    query = _ctypes.create_string_buffer(64)

    def _capture(handle, code, addr, in_size, size):
        seen.append((code, in_size))
        return (buffer, len(raw))

    monkeypatch.setattr(win32, "_property_query", lambda: query)
    monkeypatch.setattr(win32, "_device_ioctl", _capture)
    assert win32._query_text(7, "model") == "Samsung SSD 870"
    assert (win32.IOCTL_STORAGE_QUERY_PROPERTY, win32.QUERY_INPUT_SIZE) in seen
    assert win32.QUERY_INPUT_SIZE > 0

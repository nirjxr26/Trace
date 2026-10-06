"""Tribunal tests for the Linux adapter: discovery bounds, phase separation, fail-closed probe."""

import json
from pathlib import Path

import pytest

from trace_core.devices import _subprocess, linux
from trace_core.devices._subprocess import HelperFailure, run_capped
from trace_core.devices.domain import DeviceInfo, DeviceKind, UnknownCause, WpVerdict

pytestmark = pytest.mark.unit

LSBLK = {
    "blockdevices": [
        {"name": "sda", "size": 500107862016, "model": "Samsung SSD", "serial": "S1", "tran": "sata"},
        {"name": "nvme0n1", "size": 1000204886016, "model": None, "serial": "N1", "tran": "nvme"},
        {"name": "sr0", "size": 0, "model": "CD-ROM", "serial": None, "tran": "sata"},
    ]
}


def _device(name: str, **kwargs) -> DeviceInfo:
    return DeviceInfo(
        node=f"/dev/{name}",
        kind=DeviceKind.OS,
        requires_real_hardware_opt_in=True,
        size_bytes=kwargs.get("size_bytes", 1024),
        model_hint=kwargs.get("model_hint"),
    )


def test_parsed_devices_are_real_hardware_and_need_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: LSBLK)
    devices = linux.LinuxDevice().list_block_devices()
    assert [Path(d.node).name for d in devices] == ["nvme0n1", "sda", "sr0"], "deterministic order, not tree order"
    assert all(d.requires_real_hardware_opt_in for d in devices)
    assert {d.size_bytes for d in devices} == {500107862016, 1000204886016, 0}


def test_size_beyond_int4_survives_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    huge = {"blockdevices": [{"name": "sdz", "size": 9_007_199_254_740_993, "model": "big"}]}
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: huge)
    assert linux.LinuxDevice().list_block_devices()[0].size_bytes == 9_007_199_254_740_993


@pytest.mark.parametrize("hostile", [None, "", "   ", 42, {"nested": 1}, True])
def test_unusable_names_and_models_are_dropped_or_emptied(monkeypatch: pytest.MonkeyPatch, hostile: object) -> None:
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: {"blockdevices": [{"name": hostile, "model": hostile}]})
    devices = linux.LinuxDevice().list_block_devices()
    assert devices == [] or devices[0].model_hint is None


def test_enumeration_survives_a_broken_document(monkeypatch: pytest.MonkeyPatch) -> None:
    for hostile in (None, [], "text", {"blockdevices": "nope"}, {"blockdevices": [None, 5, {"name": "ok"}]}):
        monkeypatch.setattr(linux, "lsblk_json", lambda _h=hostile, **_k: _h)
        assert linux.LinuxDevice().list_block_devices() is not None


def test_enumeration_is_empty_when_lsblk_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _absent(**_k):
        raise HelperFailure(UnknownCause.TOOL_MISSING, "lsblk missing")

    monkeypatch.setattr(linux, "lsblk_json", _absent)
    assert linux.LinuxDevice().list_block_devices() == []


def test_enumeration_never_opens_a_device_for_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """[D23] list is discovery: no smartctl, no hashing, no probe."""
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: LSBLK)
    calls: list[str] = []
    monkeypatch.setattr(linux, "run_capped", lambda argv, **k: calls.append(argv[0]) or b"{}")
    monkeypatch.setattr(_subprocess, "sha256_file", lambda *a, **k: pytest.fail("list hashed a device"), raising=False)
    linux.LinuxDevice().list_block_devices()
    assert calls == [], "enumeration reached smartctl or any enrichment helper"


def test_inspect_reads_nothing_but_calls_smartctl_once(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice(dev_root=str(Path("/nonexistent-root")))
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(linux, "_sysfs_value", lambda name, key: {"serial": "S1", "transport": "sata"}.get(key))
    seen: list[list[str]] = []
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: None)
    monkeypatch.setattr(
        linux,
        "run_capped",
        lambda argv, **k: (
            seen.append(argv)
            or json.dumps({"smartctl": {"exit_status": 0}, "firmware_version": "FW1", "wwn": "0xabc"}).encode()
        ),
    )
    inspection = adapter.inspect(_device("sda"))
    assert inspection.fingerprint.firmware == "FW1"
    assert inspection.fingerprint.wwn == "0xabc"
    assert inspection.fingerprint.source == "smartctl"
    assert len(seen) == 1
    assert seen[0][:3] == ["smartctl", "-d", "sat"]


def test_smartctl_device_type_comes_only_from_a_closed_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """[D20] `-d` is derived from transport, never from serial or model bytes."""
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: None)
    for transport, expected in (("usb", "usb"), ("sata", "sat"), ("nvme", "nvme"), ("scsi", "scsi")):
        seen: list[list[str]] = []
        monkeypatch.setattr(
            linux, "_sysfs_value", lambda name, key, _t=transport: {"serial": "S", "transport": _t}.get(key)
        )
        monkeypatch.setattr(
            linux,
            "run_capped",
            lambda argv, **k: seen.append(argv) or json.dumps({"smartctl": {"exit_status": 0}}).encode(),
        )
        adapter.inspect(_device("sdx"))
        assert seen[0][2] == expected

    monkeypatch.setattr(linux, "_sysfs_value", lambda name, key: {"serial": "S", "transport": "floppy"}.get(key))
    monkeypatch.setattr(
        linux, "run_capped", lambda argv, **k: pytest.fail(f"unmapped transport reached smartctl: {argv}")
    )
    assert adapter.inspect(_device("sdy")).fingerprint.source == "os"


def test_native_fields_come_from_lsblk_not_an_invented_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`lsblk` already reports SERIAL, WWN and TRAN; reading them beats a udev guess."""
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(
        linux, "_sysfs_value", lambda name, key: pytest.fail(f"native phase fell back to sysfs for {key}")
    )
    monkeypatch.setattr(
        linux.LinuxDevice,
        "_entry",
        lambda self, name: {
            "name": name,
            "serial": "REAL1",
            "model": "RealModel",
            "tran": "nvme",
            "wwn": "0xdeadbeef",
        },
    )
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: UnknownCause.TOOL_MISSING)
    inspection = adapter.inspect(_device("sda"))
    assert inspection.fingerprint.serial.value == "REAL1"
    assert inspection.fingerprint.model == "RealModel"
    assert inspection.fingerprint.wwn == "0xdeadbeef"
    assert inspection.fingerprint.interface is linux.DeviceInterface.NVME


def test_native_serial_falls_back_through_sysfs_then_the_node(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: UnknownCause.TOOL_MISSING)
    monkeypatch.setattr(linux, "_sysfs_value", lambda name, key: "SYSFS1" if key == "serial" else None)

    monkeypatch.setattr(linux.LinuxDevice, "_entry", lambda self, name: {})
    assert adapter.inspect(_device("sda")).fingerprint.serial.value == "SYSFS1"

    monkeypatch.setattr(linux, "_sysfs_value", lambda name, key: None)
    assert adapter.inspect(_device("sda")).fingerprint.serial.value == "/dev/sda"


def test_sysfs_fallback_points_at_a_real_kernel_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(linux, "_read", lambda path: seen.append(path) or None)
    linux._sysfs_value("sda", "serial")
    assert seen == [f"{linux.SYSFS_BLOCK}/sda/serial"]


def test_a_device_name_never_becomes_a_path_outside_sys_block(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(linux, "_read", lambda path: seen.append(path) or None)
    linux._sysfs_value("../../etc/shadow", "serial")
    assert seen == [f"{linux.SYSFS_BLOCK}/../../etc/shadow/serial"]


def test_missing_lsblk_row_degrades_without_guessing(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(linux.LinuxDevice, "_entry", lambda self, name: {})
    monkeypatch.setattr(linux, "_sysfs_value", lambda name, key: None)
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: UnknownCause.TOOL_MISSING)
    fingerprint = adapter.inspect(_device("sda")).fingerprint
    assert fingerprint.serial.value == "/dev/sda"
    assert fingerprint.interface is linux.DeviceInterface.UNKNOWN
    assert fingerprint.source == "os"


def test_inspect_reuses_the_enumerated_rows_instead_of_re_running_lsblk(monkeypatch: pytest.MonkeyPatch) -> None:
    """`inspect` re-reads one device, not the whole block tree."""
    adapter = linux.LinuxDevice()
    calls: list[int] = []
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: calls.append(1) or LSBLK)
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: UnknownCause.TOOL_MISSING)
    monkeypatch.setattr(linux, "_sysfs_value", lambda name, key: pytest.fail("lsblk row was not reused"))

    devices = [d for d in adapter.list_block_devices() if d.model_hint != "CD-ROM"]
    assert len(calls) == 1
    for device in devices:
        fingerprint = adapter.inspect(device).fingerprint
        assert fingerprint.serial.value in {"S1", "N1"}
        assert fingerprint.interface is not linux.DeviceInterface.UNKNOWN
    assert len(calls) == 1, f"inspect re-ran lsblk {len(calls) - 1} extra time(s)"


def test_a_cold_inspect_still_reads_the_row_it_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    calls: list[int] = []
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: calls.append(1) or LSBLK)
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: UnknownCause.TOOL_MISSING)
    monkeypatch.setattr(linux, "_sysfs_value", lambda name, key: None)
    assert adapter.inspect(_device("sda")).fingerprint.serial.value == "S1"
    assert len(calls) == 1


def test_enumeration_refreshes_a_stale_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    first = {"blockdevices": [{"name": "sda", "serial": "OLD"}]}
    second = {"blockdevices": [{"name": "sda", "serial": "NEW"}]}
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: first)
    adapter.list_block_devices()
    assert adapter._rows["sda"]["serial"] == "OLD"
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: second)
    adapter.list_block_devices()
    assert adapter._rows["sda"]["serial"] == "NEW"


def test_enumeration_failure_clears_a_previously_cached_row(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: LSBLK)
    adapter.list_block_devices()

    def _gone(**_k):
        raise HelperFailure(UnknownCause.TOOL_MISSING, "lsblk gone")

    monkeypatch.setattr(linux, "lsblk_json", _gone)
    assert adapter.list_block_devices() == []
    assert adapter._rows == {}


def test_lsblk_row_is_looked_up_by_exact_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: LSBLK)
    adapter = linux.LinuxDevice()
    assert adapter._entry("nvme0n1")["serial"] == "N1"
    assert adapter._entry("sda")["serial"] == "S1"
    assert adapter._entry("nonexistent") == {}


def test_entry_lookup_survives_lsblk_being_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def _absent(**_k):
        raise HelperFailure(UnknownCause.TOOL_MISSING, "lsblk missing")

    monkeypatch.setattr(linux, "lsblk_json", _absent)
    assert linux.LinuxDevice()._entry("sda") == {}


def test_stderr_is_never_buffered_from_a_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hostile tool can flood stderr; it has no use once the exit has become a cause."""
    captured: dict[str, object] = {}

    class _Proc:
        stdout = b"{}"
        returncode = 0

    def _run(argv, **kwargs):
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setattr(_subprocess.subprocess, "run", _run)
    _subprocess.run_capped(["x"])
    assert captured["stderr"] is _subprocess.subprocess.DEVNULL


@pytest.mark.parametrize(
    ("cause", "stdout"),
    [
        (UnknownCause.SMARTCTL_TIMEOUT, b""),
        (UnknownCause.TOOL_MISSING, b""),
        (UnknownCause.SMARTCTL_MALFORMED, b""),
    ],
)
def test_enrichment_degrades_to_native_with_a_named_cause(
    monkeypatch: pytest.MonkeyPatch, cause: UnknownCause, stdout: bytes
) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: None)
    if cause is UnknownCause.SMARTCTL_TIMEOUT:

        def _timeout(argv, **k):
            raise HelperFailure(cause, "hung")

        monkeypatch.setattr(linux, "run_capped", _timeout)
    elif cause is UnknownCause.TOOL_MISSING:

        def _missing(argv, **k):
            raise HelperFailure(cause, "absent")

        monkeypatch.setattr(linux, "run_capped", _missing)
    else:
        monkeypatch.setattr(linux, "run_capped", lambda argv, **k: b"{not json")

    assert adapter._enrich("sda", linux.DeviceInterface.SATA)[0] is cause


def test_oversized_smartctl_output_is_discarded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(linux, "smartctl_readiness", lambda: None)
    monkeypatch.setattr(linux, "run_capped", lambda argv, **k: b"x" * 4096)
    assert adapter._enrich("sda", linux.DeviceInterface.SATA)[0] is UnknownCause.SMARTCTL_MALFORMED


def test_oversized_lsblk_output_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Proc:
        stdout = b"x" * 4096
        returncode = 0

    monkeypatch.setattr(_subprocess.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(HelperFailure) as caught:
        _subprocess.lsblk_json(cap=64)
    assert caught.value.cause is UnknownCause.SMARTCTL_MALFORMED


def test_nested_partitions_are_enumerated_too(monkeypatch: pytest.MonkeyPatch) -> None:
    nested = {"blockdevices": [{"name": "sda", "size": 10, "children": [{"name": "sda1", "size": 5}]}]}
    monkeypatch.setattr(linux, "lsblk_json", lambda **_k: nested)
    assert [Path(d.node).name for d in linux.LinuxDevice().list_block_devices()] == ["sda", "sda1"]


def test_probe_reports_read_only_only_when_every_probe_agrees(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(adapter, "_exclusive_open", lambda path: True)
    monkeypatch.setattr(linux, "read_sysfs_ro", lambda name: True)
    monkeypatch.setattr(adapter, "_blkroget", lambda path: True)
    checks, cause = adapter._probe("sda")
    assert cause is None
    assert {c.name for c in checks} == {
        linux.CHECK_EXISTENCE,
        linux.CHECK_OPEN_EXCLUSIVE,
        linux.CHECK_SYSFS_RO,
        linux.CHECK_BLKROGET,
    }


@pytest.mark.parametrize(
    ("sysfs_ro", "ioctl", "expected"),
    [
        (True, True, None),
        (False, False, None),
        (True, False, UnknownCause.SYSFS_DISAGREEMENT),
        (False, True, UnknownCause.SYSFS_DISAGREEMENT),
        (None, True, UnknownCause.SYSFS_DISAGREEMENT),
        (True, None, None),
    ],
)
def test_probe_disagreement_is_never_guessed(
    monkeypatch: pytest.MonkeyPatch, sysfs_ro: bool | None, ioctl: object, expected: object
) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(adapter, "_exclusive_open", lambda path: True)
    monkeypatch.setattr(linux, "read_sysfs_ro", lambda name: sysfs_ro)
    monkeypatch.setattr(adapter, "_blkroget", lambda path: ioctl)
    assert adapter._probe("sda")[1] is expected


def test_permission_denied_names_eacces_with_remediation(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(adapter, "_exclusive_open", lambda path: True)
    monkeypatch.setattr(linux, "read_sysfs_ro", lambda name: None)
    monkeypatch.setattr(adapter, "_blkroget", lambda path: PermissionError(13, "denied"))
    checks, cause = adapter._probe("sda")
    assert cause is UnknownCause.EACCES
    assert "elevated" in " ".join(c.detail or "" for c in checks)


def test_a_vanished_device_is_never_a_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: False)
    checks, cause = adapter._probe("sda")
    assert cause is UnknownCause.DEVICE_DISAPPEARED
    assert len(checks) == 1


def test_inspect_of_a_vanished_device_raises_device_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    from trace_core.devices.domain import DeviceGoneError

    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: False)
    with pytest.raises(DeviceGoneError):
        adapter.inspect(_device("sda"))


def test_evidence_shape_matches_the_fake_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """[D33] every adapter emits structurally identical evidence."""
    from trace_core.devices import file_device

    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(adapter, "_exclusive_open", lambda path: True)
    monkeypatch.setattr(linux, "read_sysfs_ro", lambda name: True)
    monkeypatch.setattr(adapter, "_blkroget", lambda path: True)
    linux_gate = adapter.verify(_device("sda"))

    box = Path(pytest.importorskip("tempfile").mkdtemp())
    from trace_core.devices import synthetic

    synthetic.write_disk(box / "d.dd", size=256)
    fake_gate = file_device.FileDevice(box).verify(file_device.FileDevice(box).list_block_devices()[0])

    assert tuple(c.name for c in linux_gate.evidence.checks[:1]) == (
        tuple(c.name for c in fake_gate.evidence.checks[:1])[0],
    )
    assert linux_gate.evidence.adapter_version
    assert type(linux_gate.verdict) is type(fake_gate.verdict)


def test_the_probe_never_shells_out(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = linux.LinuxDevice()
    monkeypatch.setattr(adapter, "_exists", lambda name: True)
    monkeypatch.setattr(adapter, "_exclusive_open", lambda path: True)
    monkeypatch.setattr(linux, "read_sysfs_ro", lambda name: True)
    monkeypatch.setattr(adapter, "_blkroget", lambda path: True)
    monkeypatch.setattr(linux, "run_capped", lambda argv, **k: pytest.fail(f"the probe shelled out: {argv}"))
    assert adapter.verify(_device("sda")).verdict is WpVerdict.READ_ONLY


def test_sysfs_ro_unreadable_is_unknown_not_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_text", lambda self, **k: (_ for _ in ()).throw(PermissionError("nope")))
    assert _subprocess.read_sysfs_ro("sda") is None


def test_oversized_stdout_is_refused_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Proc:
        stdout = b"y" * 32
        returncode = 0

    monkeypatch.setattr(_subprocess.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(HelperFailure):
        run_capped(["x"], cap=8)


def test_helper_argv_is_never_a_shell_string(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Proc:
        stdout = b"{}"
        returncode = 0

    def _run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setattr(_subprocess.subprocess, "run", _run)
    run_capped(["smartctl", "-j"])
    assert isinstance(captured["argv"], list)
    assert captured["shell"] is False
    assert "timeout" in captured


def test_change_token_lists_kernel_block_names_without_a_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sysfs = tmp_path / "sys" / "block"
    sysfs.mkdir(parents=True)
    (sysfs / "sda").mkdir()
    (sysfs / "nvme0n1").mkdir()
    monkeypatch.setattr(linux, "SYSFS_BLOCK", str(sysfs))
    assert linux.LinuxDevice().change_token() == ("nvme0n1", "sda")
    (sysfs / "sdb").mkdir()
    assert linux.LinuxDevice().change_token() == ("nvme0n1", "sda", "sdb")


def test_change_token_is_empty_when_sysfs_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linux, "SYSFS_BLOCK", "/nonexistent-sys-block")
    assert linux.LinuxDevice().change_token() == ()

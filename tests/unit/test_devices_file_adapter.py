"""Tribunal tests for the file adapter: determinism, evidence shape, fault modes [D33]."""

import inspect
from pathlib import Path

import pytest

from trace_core.devices import file_device, ports, synthetic
from trace_core.devices.domain import DeviceGoneError, DeviceInfo, DeviceKind, WpVerdict

pytestmark = pytest.mark.unit


def test_synthetic_content_is_deterministic() -> None:
    first = synthetic.payload(b"seed", 100)
    second = synthetic.payload(b"seed", 100)
    assert first == second
    assert synthetic.payload(b"seed", 100) != synthetic.payload(b"seed2", 100)
    assert len(synthetic.payload(b"seed", 100)) == 100
    assert synthetic.payload(b"seed", 0) == b""


def test_synthetic_serial_is_content_derived() -> None:
    assert synthetic.synthetic_serial("a" * 64).startswith("SYNTH-")


def test_write_disk_creates_missing_ancestors(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "deeper" / "disk.dd"
    assert synthetic.write_disk(target, size=64) == target
    assert target.exists()
    assert target.stat().st_size == 64


def test_absent_serial_is_deterministic_and_not_content_derived() -> None:
    first = synthetic.absent_serial("/dev/sda")
    assert first == synthetic.absent_serial("/dev/sda")
    assert first != synthetic.absent_serial("/dev/sdb")
    assert first.startswith("SYNTH-")


def test_enumeration_uses_stat_only_and_never_flags_real_hardware(device_box: Path) -> None:
    devices = file_device.FileDevice(device_box).list_block_devices()
    assert [d.node for d in devices] == [str(device_box / "disk-a.dd"), str(device_box / "disk-b.dd")]
    assert all(d.kind is DeviceKind.FILE for d in devices)
    assert all(d.requires_real_hardware_opt_in is False for d in devices)
    assert [d.size_bytes for d in devices] == [2048, 1024]


def test_enumeration_never_opens_a_device_for_content(device_box: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real_open = Path.open

    def _tracking_open(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        opened.append(self.name)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _tracking_open)
    file_device.FileDevice(device_box).list_block_devices()
    assert opened == []


def test_fingerprint_is_byte_stable_across_instances(device_box: Path) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    first = file_device.FileDevice(device_box).inspect(device)
    second = file_device.FileDevice(device_box).inspect(device)
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint.source == "synthetic"
    assert first.fingerprint.serial.value.startswith("SYNTH-")
    assert first.fingerprint.capacity_bytes == 2048


def test_protected_profile_reports_read_only(device_box: Path) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    gate = file_device.FileDevice(device_box).verify(device)
    assert gate.verdict is WpVerdict.READ_ONLY
    assert gate.evidence.platform == "fake"
    assert gate.evidence.unknown_cause is None


def test_writable_profile_reports_writable(device_box: Path) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    gate = file_device.FileDevice(device_box, behaviour=file_device.WRITABLE).verify(device)
    assert gate.verdict is WpVerdict.WRITABLE


@pytest.mark.parametrize(
    ("behaviour", "cause"),
    [
        (file_device.UNKNOWN_PROTECTION, "IOCTL_FAILURE"),
        (file_device.PERMISSION_DENIED, "EACCES"),
        (file_device.MISSING, "DEVICE_DISAPPEARED"),
    ],
)
def test_fault_profiles_yield_unknown_with_a_cause(device_box: Path, behaviour: str, cause: str) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    gate = file_device.FileDevice(device_box, behaviour=behaviour).verify(device)
    assert gate.verdict is WpVerdict.UNKNOWN
    assert gate.evidence.unknown_cause is not None
    assert gate.evidence.unknown_cause.value == cause


def test_parent_disagreement_never_guesses(device_box: Path) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    gate = file_device.FileDevice(device_box, behaviour=file_device.PARENT_DISAGREEMENT).verify(device)
    assert gate.verdict is WpVerdict.WRITABLE
    assert any(c.detail for c in gate.evidence.checks)


def test_permission_denied_carries_remediation_text(device_box: Path) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    gate = file_device.FileDevice(device_box, behaviour=file_device.PERMISSION_DENIED).verify(device)
    assert "elevated" in " ".join(c.detail or "" for c in gate.evidence.checks)


def test_evidence_shape_is_identical_across_every_profile(device_box: Path) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    shapes = set()
    for behaviour in file_device.BEHAVIOURS:
        gate = file_device.FileDevice(device_box, behaviour=behaviour).verify(device)
        shapes.add(
            (
                gate.evidence.platform,
                tuple(c.name for c in gate.evidence.checks),
                gate.evidence.adapter_version,
                type(gate.verdict),
            )
        )
    assert len(shapes) == 1


def test_one_object_satisfies_all_three_ports(device_box: Path) -> None:
    adapter = file_device.FileDevice(device_box)
    for protocol, method in (
        (ports.DeviceEnumerator, "list_block_devices"),
        (ports.DeviceInspector, "inspect"),
        (ports.WriteBlockerProbe, "verify"),
    ):
        assert inspect.signature(getattr(type(adapter), method)) == inspect.signature(getattr(protocol, method))


def test_behaviour_is_matched_by_value_not_identity(device_box: Path) -> None:
    """A profile name from config, JSON or a TUI is a runtime string, not a literal.

    Identity comparison silently fell through to the default branch and reported a
    source the caller declared PROTECTED as WRITABLE.
    """
    runtime_built = "".join(["protect", "ed"])
    assert runtime_built == file_device.PROTECTED
    assert runtime_built is not file_device.PROTECTED

    device = file_device.FileDevice(device_box).list_block_devices()[0]
    gate = file_device.FileDevice(device_box, behaviour=runtime_built).verify(device)
    assert gate.verdict is WpVerdict.READ_ONLY
    assert gate.evidence.unknown_cause is None


@pytest.mark.parametrize("behaviour", sorted(file_device.BEHAVIOURS))
def test_every_profile_survives_a_round_trip_through_its_own_name(device_box: Path, behaviour: str) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    named = "".join(list(behaviour))
    adapter = file_device.FileDevice(device_box, behaviour=named)
    assert adapter.behaviour == behaviour
    gate = adapter.verify(device)
    expected = file_device.FileDevice(device_box, behaviour=behaviour).verify(device)
    assert gate.verdict is expected.verdict
    assert gate.evidence.unknown_cause is expected.evidence.unknown_cause


def test_unknown_behaviour_is_rejected_at_construction(device_box: Path) -> None:
    with pytest.raises(ValueError, match="unknown behaviour"):
        file_device.FileDevice(device_box, behaviour="not-a-profile")


def test_enumeration_of_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert file_device.FileDevice(tmp_path / "nope").list_block_devices() == []


def test_a_subdirectory_is_never_enumerated_as_a_device(device_box: Path) -> None:
    (device_box / "nested").mkdir()
    (device_box / "nested" / "inner.dd").write_bytes(b"inner")
    nodes = [d.node for d in file_device.FileDevice(device_box).list_block_devices()]
    assert nodes == [str(device_box / "disk-a.dd"), str(device_box / "disk-b.dd")]


def test_vanished_device_inspect_is_not_a_silent_success(device_box: Path) -> None:
    device = file_device.FileDevice(device_box).list_block_devices()[0]
    Path(device.node).unlink()
    adapter = file_device.FileDevice(device_box)
    with pytest.raises(DeviceGoneError):
        adapter.inspect(device)


@pytest.mark.parametrize("hostile", ["..", ".", "a/../..", "", "/", "..\\.."])
@pytest.mark.parametrize("entry_point", ["inspect", "verify"])
def test_a_node_naming_the_root_or_its_parent_is_refused(device_box: Path, hostile: str, entry_point: str) -> None:
    info = DeviceInfo(node=hostile, kind=DeviceKind.FILE, requires_real_hardware_opt_in=False)
    adapter = file_device.FileDevice(device_box)
    call = getattr(adapter, entry_point)
    with pytest.raises(ValueError, match="Refusing"):
        call(info)


def test_a_symlink_pointing_outside_the_root_is_refused(tmp_path: Path) -> None:
    """The adapter reads evidence, so following a link out of the trust root is a leak."""
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "confidential.dd"
    secret.write_bytes(b"SECRET EVIDENCE OUTSIDE ROOT")
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "sneaky.dd").symlink_to(secret)
    except OSError:
        pytest.skip("symlink creation not permitted on this host")

    adapter = file_device.FileDevice(root)
    device = adapter.list_block_devices()[0]
    with pytest.raises(ValueError, match="escaping"):
        adapter.inspect(device)


def test_change_token_tracks_entries_without_reading_them(device_box: Path) -> None:
    adapter = file_device.FileDevice(device_box)
    assert adapter.change_token() == ("disk-a.dd", "disk-b.dd")
    (device_box / "disk-c.dd").write_bytes(b"new")
    assert adapter.change_token() == ("disk-a.dd", "disk-b.dd", "disk-c.dd")


def test_change_token_of_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert file_device.FileDevice(tmp_path / "nope").change_token() == ()

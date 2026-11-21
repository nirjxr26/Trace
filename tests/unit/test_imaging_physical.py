import hashlib
import json
from pathlib import Path

import pytest
from textual.binding import Binding
from typer.testing import CliRunner

from trace_core.audit.domain import AuditAction
from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.cli.main import app
from trace_core.core.clock import now_utc
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import AuthorizationError, ValidationError
from trace_core.devices import synthetic
from trace_core.devices.domain import (
    DeviceFingerprint,
    DeviceInfo,
    DeviceInspection,
    DeviceInterface,
    DeviceKind,
    GateCheck,
    ObservedSerial,
    ProtectionCheck,
    ProtectionEvidence,
    WpVerdict,
)
from trace_core.imaging.domain import (
    ImagingDestinationError,
    ImagingInterruptedError,
    ImagingSourceReadError,
    ImagingState,
)
from trace_core.imaging.service import ImagingService
from trace_core.imaging.source import FileSource
from trace_core.imaging.stream import PIECE_SIZE, copy_raw
from trace_core.tui.app import TAB_HINTS
from trace_core.tui.screens.cases import CasesView

pytestmark = pytest.mark.unit

NODE = r"\\.\PhysicalDrive9"
SERIAL = "PHYSICAL-9"


class FakeDeviceService:
    def __init__(self, node: str, size: int) -> None:
        self.node = node
        self.size = size
        self.allowed: list[bool] = []

    def list_devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(
                node=self.node,
                kind=DeviceKind.OS,
                requires_real_hardware_opt_in=True,
                size_bytes=self.size,
                model_hint="Fake disk",
            )
        ]

    def inspect_device(self, node: str, *, allow_real_hardware: bool = False) -> DeviceInspection:
        self.allowed.append(allow_real_hardware)
        if not allow_real_hardware:
            raise AuthorizationError("real hardware opt-in required")
        return DeviceInspection(
            device=self.list_devices()[0],
            fingerprint=DeviceFingerprint(
                serial=ObservedSerial(value=SERIAL),
                model="Fake disk",
                capacity_bytes=self.size,
                interface=DeviceInterface.SCSI,
                source="os",
            ),
            inspected_at=now_utc(),
        )

    def check_device(self, node: str, *, inspection, allow_real_hardware: bool = False) -> GateCheck:
        self.allowed.append(allow_real_hardware)
        if not allow_real_hardware:
            raise AuthorizationError("real hardware opt-in required")
        return GateCheck(
            verdict=WpVerdict.READ_ONLY,
            evidence=ProtectionEvidence(
                platform="windows",
                checks=(ProtectionCheck(name="ioctl_is_writable", result="False"),),
                adapter_version="fake-physical-v1",
                checked_at=now_utc(),
            ),
            checked_at=now_utc(),
        )


def _manager(tmp_path: Path) -> DatabaseSessionManager:
    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    manager.init_schema()
    return manager


def _case(manager: DatabaseSessionManager) -> str:
    return CaseService(manager).create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner")).number


def _image_path(root: Path, operation: object) -> Path:
    relpath = getattr(operation, "image_relpath")
    assert relpath is not None
    return root / relpath


def _manifest_path(root: Path, operation: object) -> Path:
    relpath = getattr(operation, "manifest_relpath")
    assert relpath is not None
    return root / relpath


def test_copy_raw_resumes_at_offset() -> None:
    data = b"0123456789" * 1000
    source = data[2000:]
    destination = bytearray(data[:2000])

    from io import BytesIO

    count, digest = copy_raw(BytesIO(source), BytesIO(destination), len(data), offset=2000)

    assert count == len(source)
    assert digest == hashlib.sha256(source).hexdigest()


def test_copy_raw_raises_interrupted_on_cancel() -> None:
    from io import BytesIO

    with pytest.raises(ImagingInterruptedError, match="cancelled"):
        copy_raw(BytesIO(b"abc"), BytesIO(), 3, cancelled=lambda: True)


def test_physical_requires_explicit_opt_in(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=2048)
    devices = FakeDeviceService(str(source), source.stat().st_size)
    service = ImagingService(manager, device_service=devices)
    operation = service.reserve(number)

    with pytest.raises(AuthorizationError):
        service.acquire(operation.id, str(source))

    assert devices.allowed == []
    assert service.list_for_case(number)[0].state is ImagingState.PREPARING


def test_physical_acquire_produces_byte_verified_image(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=4096)
    devices = FakeDeviceService(str(source), source.stat().st_size)
    service = ImagingService(manager, device_service=devices)
    operation = service.reserve(number)

    completed = service.acquire(operation.id, str(source), allow_real_hardware=True)

    assert completed.state is ImagingState.BYTE_VERIFIED
    assert completed.source_kind is not None
    assert completed.source_kind.value == "OS"
    assert devices.allowed
    assert all(devices.allowed)
    image = _image_path(temp_storage, completed)
    assert image.read_bytes() == source.read_bytes()
    actions = [
        event.action for event in AuditService(manager).list_events(AuditFilterDto(case_number=number, limit=20))
    ]
    assert AuditAction.IMAGING_STARTED in actions
    assert AuditAction.IMAGING_COMPLETED in actions


def test_interrupted_physical_acquisition_resumes(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=1024 * 1024 + 1024)
    devices = FakeDeviceService(str(source), source.stat().st_size)
    service = ImagingService(manager, device_service=devices)
    operation = service.reserve(number)
    position = {"done": 0}

    def progress(done: int, total: int) -> None:
        position["done"] = done

    with pytest.raises(ImagingInterruptedError):
        service.acquire(
            operation.id,
            str(source),
            allow_real_hardware=True,
            progress=progress,
            cancelled=lambda: position["done"] >= 1024 * 1024,
        )

    interrupted = service.list_for_case(number)[0]
    assert interrupted.state is ImagingState.INTERRUPTED
    assert position["done"] >= 1024 * 1024

    completed = service.acquire(interrupted.id, str(source), allow_real_hardware=True)

    assert completed.state is ImagingState.BYTE_VERIFIED
    assert completed.copied_bytes == source.stat().st_size
    image = _image_path(temp_storage, completed)
    assert image.read_bytes() == source.read_bytes()


def test_acquiring_state_recovers_after_verification_mark_failure(
    tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=4096)
    devices = FakeDeviceService(str(source), source.stat().st_size)
    service = ImagingService(manager, device_service=devices)
    operation = service.reserve(number)
    original = ImagingService._mark_verifying
    attempts = {"count": 0}

    def fail_once(self, *args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("database unavailable")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ImagingService, "_mark_verifying", fail_once)
    with pytest.raises(RuntimeError, match="database unavailable"):
        service.acquire(operation.id, str(source), allow_real_hardware=True)

    assert service.list_for_case(number)[0].state is ImagingState.ACQUIRING
    monkeypatch.setattr(ImagingService, "_mark_verifying", original)
    completed = service.acquire(operation.id, str(source), allow_real_hardware=True)

    assert completed.state is ImagingState.BYTE_VERIFIED
    assert _image_path(temp_storage, completed).read_bytes() == source.read_bytes()


def test_cli_physical_flag_reaches_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    seen: dict[str, object] = {}

    def fake_acquire(self, operation_id, source_node, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            id=operation_id, acquisition_sha256="a" * 64, copied_bytes=0, image_relpath="x", manifest_relpath="y"
        )

    monkeypatch.setattr(ImagingService, "acquire", fake_acquire)
    result = CliRunner().invoke(
        app,
        ["case", "imaging-acquire", "00000000-0000-0000-0000-000000000001", "--source", NODE, "--physical", "--yes"],
    )

    assert result.exit_code == 0
    assert seen.get("allow_real_hardware") is True


def test_verification_detects_image_corruption(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=2048)
    devices = FakeDeviceService(str(source), source.stat().st_size)
    service = ImagingService(manager, device_service=devices)
    operation = service.reserve(number)
    completed = service.acquire(operation.id, str(source), allow_real_hardware=True)

    assert service.verify_image(completed.id) is True

    image = _image_path(temp_storage, completed)
    with image.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"X")

    assert service.verify_image(completed.id) is False


def test_cli_verify_reports_a_corrupted_image(
    tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=2048)
    devices = FakeDeviceService(str(source), source.stat().st_size)
    service = ImagingService(manager, device_service=devices)
    operation = service.acquire(service.reserve(number).id, str(source), allow_real_hardware=True)
    monkeypatch.setattr("trace_core.core.service.db_manager", manager)
    image = _image_path(temp_storage, operation)
    with image.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"X")

    result = CliRunner().invoke(app, ["case", "imaging-verify", str(operation.id)])

    assert result.exit_code != 0
    assert "Verification Failed" in result.stdout


def test_tui_advertises_physical_acquire_binding() -> None:
    keys = {str(binding.key) for binding in CasesView.BINDINGS if isinstance(binding, Binding)}
    assert "G" in keys
    assert "V" in keys
    assert "G Physical" in TAB_HINTS["cases"]
    assert "V Verify" in TAB_HINTS["cases"]


def test_manifest_carries_raw_format_and_piecewise_hashes(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=PIECE_SIZE + 1024)
    service = ImagingService(manager)
    completed = service.acquire(service.reserve(number).id, str(source))

    assert completed.state is ImagingState.BYTE_VERIFIED
    manifest_path = _manifest_path(temp_storage, completed)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["format"] == "RAW"
    assert payload["manifest_version"] == "trace-imaging-manifest-v1"
    assert payload["piecewise"]["algorithm"] == "SHA-256"
    assert payload["piecewise"]["chunk_size"] == PIECE_SIZE
    assert payload["piecewise"]["count"] == 2
    raw = source.read_bytes()
    assert payload["piecewise"]["hashes"] == [
        hashlib.sha256(raw[:PIECE_SIZE]).hexdigest(),
        hashlib.sha256(raw[PIECE_SIZE:]).hexdigest(),
    ]


def test_tampered_piecewise_hash_fails_reverification(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=PIECE_SIZE + 1024)
    service = ImagingService(manager)
    completed = service.acquire(service.reserve(number).id, str(source))
    manifest_path = _manifest_path(temp_storage, completed)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["piecewise"]["hashes"][0] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    assert service.verify_image(completed.id) is False


def test_bad_region_is_zero_filled_and_recorded(
    tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=2 * 1024 * 1024)
    service = ImagingService(manager)
    original = FileSource.read
    calls = {"count": 0}

    def fail_second(self: FileSource, size: int) -> bytes:
        calls["count"] += 1
        if calls["count"] == 2:
            raise ImagingSourceReadError("simulated bad sector")
        return original(self, size)

    monkeypatch.setattr(FileSource, "read", fail_second)
    completed = service.acquire(service.reserve(number).id, str(source))

    assert completed.state is ImagingState.BYTE_VERIFIED
    manifest_path = _manifest_path(temp_storage, completed)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(payload["bad_regions"]) == 1
    assert payload["bad_regions"][0]["offset"] == 1024 * 1024
    assert payload["bad_regions"][0]["length"] == 1024 * 1024
    image = _image_path(temp_storage, completed).read_bytes()
    assert image[: 1024 * 1024] == source.read_bytes()[: 1024 * 1024]
    assert image[1024 * 1024 :] == b"\0" * (1024 * 1024)


def test_sealed_image_roundtrip_and_wrong_passphrase(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=4096)
    service = ImagingService(manager)
    completed = service.acquire(service.reserve(number).id, str(source))

    encryption = service.seal_image(completed.id, "correct-passphrase")
    sealed_path = temp_storage / encryption.sealed_relpath
    assert sealed_path.is_file()

    with pytest.raises(ImagingDestinationError, match="already sealed"):
        service.seal_image(completed.id, "another-passphrase")
    assert sealed_path.is_file()

    out = tmp_path / "unsealed.raw"
    service.open_sealed_image(completed.id, "correct-passphrase", out)
    assert out.read_bytes() == source.read_bytes()

    with pytest.raises(ValidationError, match="wrong passphrase or corrupted"):
        service.open_sealed_image(completed.id, "wrong-passphrase", tmp_path / "wrong.raw")


def test_seal_refuses_image_changed_after_verification(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=4096)
    service = ImagingService(manager)
    completed = service.acquire(service.reserve(number).id, str(source))
    image = _image_path(temp_storage, completed)
    with image.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"X")

    with pytest.raises(ValidationError, match="changed before it could be sealed"):
        service.seal_image(completed.id, "passphrase")

    assert not (image.parent / "image.raw.sealed").exists()
    assert not (image.parent / "seal.json").exists()


def test_verify_recovery_keeps_bad_regions(tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "disk.dd", size=2 * 1024 * 1024)
    service = ImagingService(manager)
    original = FileSource.read
    calls = {"count": 0}

    def fail_second(self: FileSource, size: int) -> bytes:
        calls["count"] += 1
        if calls["count"] == 2:
            raise ImagingSourceReadError("simulated bad sector")
        return original(self, size)

    monkeypatch.setattr(FileSource, "read", fail_second)
    original_verify = ImagingService._verify_and_publish
    attempts = {"count": 0}

    def fail_once(self, *args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("verification unavailable")
        return original_verify(self, *args, **kwargs)

    monkeypatch.setattr(ImagingService, "_verify_and_publish", fail_once)
    with pytest.raises(RuntimeError, match="verification unavailable"):
        service.acquire(service.reserve(number).id, str(source))

    interrupted = service.list_for_case(number)[0]
    assert interrupted.state is ImagingState.VERIFYING
    monkeypatch.setattr(ImagingService, "_verify_and_publish", original_verify)
    completed = service.acquire(interrupted.id, str(source))

    payload = json.loads(_manifest_path(temp_storage, completed).read_text(encoding="utf-8"))
    assert completed.state is ImagingState.BYTE_VERIFIED
    assert len(payload["bad_regions"]) == 1

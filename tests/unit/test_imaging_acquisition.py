import hashlib
import json
from pathlib import Path

import pytest

from trace_core.audit.domain import AuditAction
from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.settings import settings
from trace_core.devices import synthetic
from trace_core.devices.domain import WriteProtectionError
from trace_core.devices.file_device import WRITABLE, FileDevice
from trace_core.devices.service import DeviceService
from trace_core.imaging.domain import (
    ImagingDestinationExistsError,
    ImagingFailure,
    ImagingReadbackError,
    ImagingSourceUnavailableError,
    ImagingState,
)
from trace_core.imaging.service import ImagingService

pytestmark = pytest.mark.unit


def _manager(tmp_path: Path) -> DatabaseSessionManager:
    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    manager.init_schema()
    return manager


def _case(manager: DatabaseSessionManager) -> str:
    return CaseService(manager).create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner")).number


def test_acquire_copies_verifies_and_publishes_fixture_image(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=4096)
    service = ImagingService(manager)
    operation = service.reserve(number)

    completed = service.acquire(operation.id, str(source))

    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert completed.state is ImagingState.BYTE_VERIFIED
    assert completed.expected_bytes == 4096
    assert completed.copied_bytes == 4096
    assert completed.acquisition_sha256 == digest
    assert completed.readback_sha256 == digest
    assert completed.image_relpath is not None
    assert completed.manifest_relpath is not None
    image = settings.storage_root / completed.image_relpath
    manifest = settings.storage_root / completed.manifest_relpath
    assert image.read_bytes() == source.read_bytes()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["operation_id"] == str(operation.id)
    assert payload["case_number"] == number
    assert payload["acquisition_sha256"] == digest
    assert payload["byte_integrity"] == "verified"
    assert not (image.parent / "image.partial").exists()
    assert CaseService(manager).close_case(number, reason="finished").status.value == "CLOSED"


def test_acquisition_is_audited_in_the_transaction(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=2048)
    service = ImagingService(manager)
    operation = service.reserve(number)

    service.acquire(operation.id, str(source))

    actions = [
        event.action for event in AuditService(manager).list_events(AuditFilterDto(case_number=number, limit=20))
    ]
    assert AuditAction.IMAGING_STARTED in actions
    assert AuditAction.IMAGING_VERIFYING in actions
    assert AuditAction.IMAGING_COMPLETED in actions
    assert AuditService(manager).verify().is_valid


def test_missing_source_leaves_reservation_preparing(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    service = ImagingService(manager)
    operation = service.reserve(number)

    with pytest.raises(ImagingSourceUnavailableError):
        service.acquire(operation.id, str(tmp_path / "missing.dd"))

    assert service.list_for_case(number)[0].state is ImagingState.PREPARING


def test_explicit_missing_source_does_not_select_same_named_fixture(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    fixture_root = tmp_path / "fixtures"
    synthetic.write_disk(fixture_root / "fixture.dd", size=1024)
    service = ImagingService(manager)
    operation = service.reserve(number)

    with pytest.raises(ImagingSourceUnavailableError):
        service.acquire(operation.id, str(tmp_path / "other" / "fixture.dd"), fixture_root=fixture_root)

    assert service.list_for_case(number)[0].state is ImagingState.PREPARING


def test_writable_source_is_refused_before_the_reservation_is_claimed(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=1024)
    adapter = FileDevice(tmp_path, behaviour=WRITABLE)
    service = ImagingService(
        manager, device_service=DeviceService(manager, enumerator=adapter, inspector=adapter, probe=adapter)
    )
    operation = service.reserve(number)

    with pytest.raises(WriteProtectionError):
        service.acquire(operation.id, str(source))

    assert service.list_for_case(number)[0].state is ImagingState.PREPARING


def test_existing_destination_directory_fails_the_claimed_operation(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=1024)
    service = ImagingService(manager)
    operation = service.reserve(number)
    operation_dir = settings.storage_root / "cases" / number / "imaging" / str(operation.id)
    operation_dir.mkdir(parents=True)

    with pytest.raises(ImagingDestinationExistsError, match="already exists"):
        service.acquire(operation.id, str(source))

    stored = service.list_for_case(number)[0]
    assert stored.state is ImagingState.FAILED
    assert stored.failure_category is ImagingFailure.DESTINATION_EXISTS
    assert CaseService(manager).close_case(number, reason="finished").status.value == "CLOSED"


def test_readback_mismatch_quarantines_the_image(
    tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=1024)
    service = ImagingService(manager)
    operation = service.reserve(number)
    monkeypatch.setattr("trace_core.imaging.service.verify_image_with_pieces", lambda *args, **kwargs: (False, ()))

    with pytest.raises(ImagingReadbackError):
        service.acquire(operation.id, str(source))

    stored = service.list_for_case(number)[0]
    assert stored.state is ImagingState.QUARANTINED
    assert stored.failure_category is ImagingFailure.READBACK_MISMATCH


def test_manifest_failure_quarantines_the_published_image(
    tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=1024)
    service = ImagingService(manager)
    operation = service.reserve(number)

    def refuse(*args: object, **kwargs: object) -> None:
        raise ImagingDestinationExistsError("The manifest already exists; it was not overwritten.")

    monkeypatch.setattr("trace_core.imaging.service.write_manifest", refuse)
    with pytest.raises(ImagingDestinationExistsError):
        service.acquire(operation.id, str(source))

    stored = service.list_for_case(number)[0]
    assert stored.state is ImagingState.QUARANTINED
    assert stored.failure_category is ImagingFailure.DESTINATION_EXISTS


def test_source_change_during_read_fails_the_operation(
    tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.imaging.domain import ImagingSourceChangedError
    from trace_core.imaging.source import FileSource

    manager = _manager(tmp_path)
    number = _case(manager)
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=1024)
    service = ImagingService(manager)
    operation = service.reserve(number)

    def changed(self: FileSource) -> None:
        raise ImagingSourceChangedError("The fixture source changed while it was being read.")

    monkeypatch.setattr(FileSource, "verify_unchanged", changed)
    with pytest.raises(ImagingSourceChangedError):
        service.acquire(operation.id, str(source))

    stored = service.list_for_case(number)[0]
    assert stored.state is ImagingState.FAILED
    assert stored.failure_category is ImagingFailure.SOURCE_CHANGED

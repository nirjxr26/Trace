import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from trace_core.audit.domain import AuditAction
from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.cli.main import app
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import AuthorizationError
from trace_core.core.settings import settings
from trace_core.devices import synthetic
from trace_core.imaging.domain import (
    BlockerMode,
    ImagingSource,
    ImagingSourceKind,
    ImagingSourceUnavailableError,
    ImagingState,
)
from trace_core.imaging.service import ImagingService

pytestmark = pytest.mark.unit

NODE = "\\\\.\\PhysicalDrive9"


def _manager(tmp_path: Path) -> DatabaseSessionManager:
    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    manager.init_schema()
    return manager


def _os_source(*, hardware: bool = False) -> ImagingSource:
    from trace_core.core.clock import now_utc

    return ImagingSource(
        node=NODE,
        kind=ImagingSourceKind.OS,
        serial="SERIAL",
        model="MODEL",
        size_bytes=1024,
        protection="READ_ONLY",
        adapter="synthetic",
        synthetic=True,
        inspected_at=now_utc(),
        hardware_write_block=hardware,
        blocker_mode=BlockerMode.HARDWARE if hardware else BlockerMode.NONE,
    )


def test_blocker_mode_defaults_to_none() -> None:
    from uuid import uuid4

    from trace_core.core.clock import now_utc
    from trace_core.imaging.domain import ImagingManifest, ImagingOperation, ImagingPiecewise

    operation = ImagingOperation(
        id=uuid4(),
        case_id=uuid4(),
        case_number="2026-CR-0001",
        state=ImagingState.PREPARING,
        created_at=now_utc(),
        created_by="examiner",
    )
    manifest = ImagingManifest(
        operation_id=uuid4(),
        case_id=uuid4(),
        case_number="2026-CR-0001",
        source=_os_source(),
        expected_bytes=1024,
        copied_bytes=1024,
        acquisition_sha256="a" * 64,
        readback_sha256="a" * 64,
        image_relpath="image.raw",
        piecewise=ImagingPiecewise(chunk_size=1024, count=0),
        created_at=now_utc(),
        finished_at=now_utc(),
        tool_version="0.6.0",
    )
    assert operation.blocker_mode is BlockerMode.NONE
    assert manifest.blocker_mode is BlockerMode.NONE


def test_no_blocker_conflicts_with_other_modes() -> None:
    device = SimpleNamespace(requires_real_hardware_opt_in=False)
    with pytest.raises(AuthorizationError):
        ImagingService._require_write_block_opt_ins(device, NODE, True, True, False, True)
    with pytest.raises(AuthorizationError):
        ImagingService._require_write_block_opt_ins(device, NODE, True, False, True, True)
    ImagingService._require_write_block_opt_ins(device, NODE, True, False, False, True)


def test_start_details_carry_blocker_mode_and_non_evidentiary_flag() -> None:
    no_blocker = ImagingService._start_details(_os_source(), (), resumed=False)
    assert no_blocker["blocker_mode"] == "NONE"
    assert no_blocker["non_evidentiary"] is True
    hardware = ImagingService._start_details(_os_source(hardware=True), (), resumed=False)
    assert hardware["blocker_mode"] == "HARDWARE"
    assert hardware["non_evidentiary"] is False


def test_resume_with_mismatched_blocker_mode_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("trace_core.imaging.service.read_checkpoint", lambda path: {"blocker_mode": "HARDWARE"})
    with pytest.raises(ImagingSourceUnavailableError):
        ImagingService._require_blocker_mode_match(_os_source(), (None, None, Path("checkpoint")))
    monkeypatch.setattr("trace_core.imaging.service.read_checkpoint", lambda path: None)
    ImagingService._require_blocker_mode_match(_os_source(), (None, None, Path("checkpoint")))


def test_fixture_acquisition_records_no_blocker_mode(tmp_path: Path, temp_storage: Path) -> None:
    manager = _manager(tmp_path)
    number = CaseService(manager).create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner")).number
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=2048)
    service = ImagingService(manager)
    operation = service.reserve(number)

    completed = service.acquire(operation.id, str(source), no_write_blocker=True)

    assert completed.state is ImagingState.BYTE_VERIFIED
    assert completed.blocker_mode is BlockerMode.NONE
    assert completed.acquisition_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert completed.manifest_relpath is not None
    manifest = json.loads((settings.storage_root / completed.manifest_relpath).read_text(encoding="utf-8"))
    assert manifest["blocker_mode"] == "NONE"
    events = AuditService(manager).list_events(AuditFilterDto(case_number=number, limit=20))
    started = [event for event in events if event.action is AuditAction.IMAGING_STARTED]
    assert started
    details = json.loads(started[0].payload_json)["details"]
    assert details["blocker_mode"] == "NONE"
    assert details["non_evidentiary"] is True


def test_cli_no_write_blocker_flag_reaches_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_acquire(self, operation_id, source_node, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            id=operation_id,
            acquisition_sha256="a" * 64,
            copied_bytes=0,
            image_relpath="x",
            manifest_relpath="y",
            blocker_mode=BlockerMode.NONE,
        )

    monkeypatch.setattr(ImagingService, "acquire", fake_acquire)
    result = CliRunner().invoke(
        app,
        [
            "case",
            "imaging-acquire",
            "00000000-0000-0000-0000-000000000001",
            "--source",
            NODE,
            "--no-write-blocker",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert seen.get("no_write_blocker") is True
    assert "NOT EVIDENTIARY" in result.output


@pytest.mark.anyio
async def test_progress_popup_shows_no_blocker_label() -> None:
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.imaging import ImagingProgressModal, ImagingView

    assert any(
        getattr(binding, "key", None) == "b" and getattr(binding, "action", None) == "acquire_no_blocker"
        for binding in ImagingView.BINDINGS
    )
    app = TraceApp()
    async with app.run_test(size=(90, 24)) as pilot:
        app.push_screen(ImagingProgressModal(preview=True, no_blocker=True))
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, ImagingProgressModal)
        label = str(modal.query_one("#progress-no-blocker").render())
        assert "NO WRITE BLOCKER · NOT EVIDENTIARY" in label

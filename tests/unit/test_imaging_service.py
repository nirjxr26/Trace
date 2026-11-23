from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, current_thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update

from trace_core.audit.domain import AuditAction
from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.cases.domain import Case
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.repository import SqlAlchemyCaseRepository
from trace_core.cases.service import CaseService, InvalidCaseStateError
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import AuthorizationError, NotFoundError
from trace_core.devices.operation_state import forensic_operation_active
from trace_core.imaging.domain import ImagingFailure, ImagingState
from trace_core.imaging.models import ImagingOperationModel
from trace_core.imaging.service import ImagingService
from trace_core.updates.gate import ForensicOperationGate, GateDecision
from trace_core.updates.lock import update_lock

pytestmark = pytest.mark.unit


def test_reservation_is_case_linked_audited_and_blocks_close_and_archive(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    imaging = ImagingService(session_manager)

    operation = imaging.reserve(case.number)

    assert operation.case_id == case.id
    assert operation.case_number == case.number
    assert operation.state is ImagingState.PREPARING
    assert operation.created_at.utcoffset() == timedelta(0)
    assert [item.id for item in imaging.list_for_case(case.number)] == [operation.id]
    events = AuditService(session_manager).list_events(AuditFilterDto(action=AuditAction.IMAGING_RESERVED))
    assert len(events) == 1
    assert str(operation.id) in events[0].payload_json
    assert AuditService(session_manager).verify().is_valid
    with pytest.raises(InvalidCaseStateError, match="unresolved imaging"):
        service.close_case(case.number, reason="finished")
    with pytest.raises(InvalidCaseStateError, match="unresolved imaging"):
        service.delete_case(case.number)
    with pytest.raises(InvalidCaseStateError, match="unresolved imaging"):
        imaging.reserve(case.number)


def test_abandoning_reservation_is_audited_and_unblocks_case(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    imaging = ImagingService(session_manager)
    operation = imaging.reserve(case.number)

    abandoned = imaging.abandon(operation.id)

    assert abandoned.state is ImagingState.FAILED
    events = AuditService(session_manager).list_events(AuditFilterDto(action=AuditAction.IMAGING_ABANDONED))
    assert len(events) == 1
    assert service.close_case(case.number, reason="finished").status.value == "CLOSED"


def test_abandoning_an_interrupted_acquisition_marks_it_failed_and_unblocks_case(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    imaging = ImagingService(session_manager)
    operation = imaging.reserve(case.number)
    with session_manager.session() as session:
        session.execute(
            update(ImagingOperationModel)
            .where(ImagingOperationModel.id == operation.id)
            .values(state=ImagingState.ACQUIRING.value)
        )
        session.commit()

    abandoned = imaging.abandon(operation.id)

    assert abandoned.state is ImagingState.FAILED
    assert abandoned.failure_category is ImagingFailure.INTERRUPTED
    events = AuditService(session_manager).list_events(AuditFilterDto(action=AuditAction.IMAGING_FAILED))
    assert len(events) == 1
    assert "INTERRUPTED" in events[0].payload_json
    assert service.close_case(case.number, reason="finished").status.value == "CLOSED"


def test_imaging_history_remains_queryable_after_case_purge(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    imaging = ImagingService(session_manager)
    operation = imaging.reserve(case.number)
    imaging.abandon(operation.id)
    service.delete_case(case.number)
    service.delete_case(case.number, purge=True)

    assert [item.id for item in imaging.list_for_case(case.number.lower())] == [operation.id]


def test_operation_state_blocks_updates_until_reservation_is_abandoned(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    imaging = ImagingService(session_manager)
    assert not forensic_operation_active(session_manager)

    operation = imaging.reserve(case.number)
    assert forensic_operation_active(session_manager)

    imaging.abandon(operation.id)
    assert not forensic_operation_active(session_manager)


def test_reservation_rejects_closed_and_archived_cases(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    closed = service.create_case(CaseCreateDto(title="Closed", lead_examiner="Examiner"))
    archived = service.create_case(CaseCreateDto(title="Archived", lead_examiner="Examiner"))
    service.close_case(closed.number, reason="finished")
    service.delete_case(archived.number)
    imaging = ImagingService(session_manager)

    for case in (closed, archived):
        with pytest.raises(InvalidCaseStateError, match="non-archived case"):
            imaging.reserve(case.number)


def test_unknown_reservation_cannot_be_abandoned(session_manager: DatabaseSessionManager) -> None:
    imaging = ImagingService(session_manager)
    operation_id = uuid4()
    with pytest.raises(NotFoundError):
        imaging.abandon(operation_id)


def test_denied_reservation_does_not_create_operation(
    service: CaseService, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))

    def deny(*args: object, **kwargs: object) -> None:
        raise AuthorizationError("denied")

    monkeypatch.setattr("trace_core.imaging.service.require_mutator", deny)
    imaging = ImagingService(session_manager)
    with pytest.raises(AuthorizationError, match="denied"):
        imaging.reserve(case.number)

    assert not forensic_operation_active(session_manager)
    assert not AuditService(session_manager).list_events(AuditFilterDto(action=AuditAction.IMAGING_RESERVED))


def test_update_gate_reports_unknown_when_operation_database_is_unavailable(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session_manager, "session", unavailable)
    gate = ForensicOperationGate(active_probe=lambda _: forensic_operation_active(session_manager))
    assert gate.can_install_update() is GateDecision.UNKNOWN


def test_failed_audit_rolls_back_reservation(
    service: CaseService, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))

    def fail_record(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditService, "record", fail_record)
    imaging = ImagingService(session_manager)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        imaging.reserve(case.number)

    monkeypatch.undo()
    assert service.close_case(case.number, reason="finished").status.value == "CLOSED"


def test_failed_abandon_audit_keeps_case_blocked(
    service: CaseService, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    imaging = ImagingService(session_manager)
    operation = imaging.reserve(case.number)

    def fail_record(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditService, "record", fail_record)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        imaging.abandon(operation.id)

    monkeypatch.undo()
    with pytest.raises(InvalidCaseStateError, match="unresolved imaging"):
        service.close_case(case.number, reason="finished")


def test_terminal_quarantine_does_not_block_case_close_or_updates(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    operation = ImagingService(session_manager).reserve(case.number)
    with session_manager.session() as session:
        session.execute(
            update(ImagingOperationModel)
            .where(ImagingOperationModel.id == operation.id)
            .values(state=ImagingState.QUARANTINED.value, failure_category=ImagingFailure.READBACK_MISMATCH.value)
        )
        session.commit()

    assert not forensic_operation_active(session_manager)
    assert service.close_case(case.number, reason="finished").status.value == "CLOSED"


def test_unrecognized_operation_state_blocks_case_close(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    operation = ImagingService(session_manager).reserve(case.number)
    with session_manager.session() as session:
        session.execute(
            update(ImagingOperationModel).where(ImagingOperationModel.id == operation.id).values(state="UNRECOGNIZED")
        )
        session.commit()

    with pytest.raises(InvalidCaseStateError, match="unresolved imaging"):
        service.close_case(case.number, reason="finished")


def test_reservation_and_case_close_cannot_both_succeed(tmp_path: Path) -> None:
    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    manager.init_schema()
    cases = CaseService(manager)
    case = cases.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    barrier = Barrier(2)

    def reserve() -> str:
        barrier.wait()
        try:
            ImagingService(manager).reserve(case.number)
        except InvalidCaseStateError:
            return "reservation blocked"
        return "reserved"

    def close() -> str:
        barrier.wait()
        try:
            cases.close_case(case.number, reason="finished")
        except InvalidCaseStateError:
            return "close blocked"
        return "closed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservation = executor.submit(reserve)
        closure = executor.submit(close)
        results = {reservation.result(timeout=45), closure.result(timeout=45)}

    assert results in ({"reserved", "close blocked"}, {"closed", "reservation blocked"})


def test_reservation_waits_for_update_lock(tmp_path: Path) -> None:
    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    manager.init_schema()
    case = CaseService(manager).create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    started = Event()

    def reserve() -> ImagingState:
        started.set()
        return ImagingService(manager).reserve(case.number).state

    with ThreadPoolExecutor(max_workers=1) as executor:
        with update_lock():
            future = executor.submit(reserve)
            assert started.wait(timeout=5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.2)
        assert future.result(timeout=20) is ImagingState.PREPARING


@pytest.mark.parametrize("first", ["reservation", "closure"])
def test_case_lock_serializes_both_reservation_and_closure_orderings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: str
) -> None:
    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    manager.init_schema()
    cases = CaseService(manager)
    case = cases.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    original_lock = SqlAlchemyCaseRepository.lock_for_imaging
    locked = Event()
    release = Event()
    second_started = Event()

    def controlled_lock(repo: SqlAlchemyCaseRepository, case_id: UUID) -> Case | None:
        result = original_lock(repo, case_id)
        if current_thread().name == first:
            locked.set()
            assert release.wait(timeout=20)
        return result

    monkeypatch.setattr(SqlAlchemyCaseRepository, "lock_for_imaging", controlled_lock)

    def act(action: str) -> str:
        current_thread().name = action
        if action != first:
            second_started.set()
        try:
            if action == "reservation":
                ImagingService(manager).reserve(case.number)
            else:
                cases.close_case(case.number, reason="finished")
        except InvalidCaseStateError:
            return f"{action} blocked"
        return f"{action} succeeded"

    second = "closure" if first == "reservation" else "reservation"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(act, first)
        assert locked.wait(timeout=10)
        second_future = executor.submit(act, second)
        try:
            assert second_started.wait(timeout=5)
            with pytest.raises(TimeoutError):
                second_future.result(timeout=0.2)
        finally:
            release.set()
        assert first_future.result(timeout=20) == f"{first} succeeded"
        assert second_future.result(timeout=20) == f"{second} blocked"

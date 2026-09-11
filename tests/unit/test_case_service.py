"""Unit tests for Case application service using in-memory database."""

import pytest

from trace_core.adapters.db.session import DatabaseSessionManager
from trace_core.application.cases import (
    CaseNotFoundError,
    CaseService,
    DuplicateCaseNumberError,
    InvalidCaseStateError,
)
from trace_core.application.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseUpdateDto,
)
from trace_core.domain.models.case import CaseStatus


@pytest.fixture
def service() -> CaseService:
    # Use SQLite in-memory for lightning-fast, isolated unit testing
    session_mgr = DatabaseSessionManager("sqlite:///:memory:")
    session_mgr.init_schema()
    return CaseService(session_mgr)


def test_create_and_get_case(service: CaseService) -> None:
    dto = CaseCreateDto(
        number="2026-TEST-0001",
        title="Laptop Drive Analysis",
        lead_examiner="Investigator A",
        description="Initial acquisition",
        tags=["laptop", "ssd"],
    )
    created = service.create_case(dto)
    assert created.number == "2026-TEST-0001"
    assert created.title == "Laptop Drive Analysis"
    assert created.status == CaseStatus.OPEN

    # Query by Case Number
    fetched = service.get_case("2026-TEST-0001")
    assert fetched.id == created.id

    # Query by UUID string
    by_uuid = service.get_case(str(created.id))
    assert by_uuid.number == created.number


def test_duplicate_case_number_raises(service: CaseService) -> None:
    dto = CaseCreateDto(
        number="2026-DUP-0001",
        title="First Case",
        lead_examiner="Investigator A",
    )
    service.create_case(dto)

    with pytest.raises(DuplicateCaseNumberError):
        service.create_case(dto)


def test_update_case(service: CaseService) -> None:
    dto = CaseCreateDto(
        number="2026-UPDATE-0001",
        title="Old Title",
        lead_examiner="Examiner 1",
    )
    case = service.create_case(dto)

    update_dto = CaseUpdateDto(
        title="Updated Title",
        notes="Added critical note",
        tags=["updated"],
    )
    updated = service.update_case(case.number, update_dto)
    assert updated.title == "Updated Title"
    assert updated.notes == "Added critical note"
    assert updated.tags == ["updated"]


def test_close_case(service: CaseService) -> None:
    dto = CaseCreateDto(
        number="2026-CLOSE-0001",
        title="Close Test",
        lead_examiner="Examiner 1",
    )
    service.create_case(dto)

    closed = service.close_case("2026-CLOSE-0001", reason="Completed")
    assert closed.status == CaseStatus.CLOSED
    assert closed.closed_at is not None


def test_soft_delete_and_purge(service: CaseService) -> None:
    dto = CaseCreateDto(
        number="2026-DEL-0001",
        title="Delete Test",
        lead_examiner="Examiner 1",
    )
    service.create_case(dto)

    # Soft delete
    assert service.delete_case("2026-DEL-0001", purge=False) is True

    # By default, list does not include soft deleted
    active = service.list_cases(CaseFilterDto(include_deleted=False))
    assert not any(c.number == "2026-DEL-0001" for c in active)

    # With include_deleted=True, it appears
    all_cases = service.list_cases(CaseFilterDto(include_deleted=True))
    assert any(c.number == "2026-DEL-0001" and c.is_deleted for c in all_cases)

    # Permanent purge
    assert service.delete_case("2026-DEL-0001", purge=True) is True
    with pytest.raises(CaseNotFoundError):
        service.get_case("2026-DEL-0001")


def test_cannot_update_closed_case(service: CaseService) -> None:
    dto = CaseCreateDto(
        number="2026-SEALED-0001",
        title="Sealed Case",
        lead_examiner="Examiner 1",
    )
    service.create_case(dto)
    service.close_case("2026-SEALED-0001")

    with pytest.raises(InvalidCaseStateError, match="Reopen the case"):
        service.update_case("2026-SEALED-0001", CaseUpdateDto(title="Illegal Edit"))


def test_cannot_update_deleted_case(service: CaseService) -> None:
    dto = CaseCreateDto(
        number="2026-ARCHIVED-0001",
        title="Archived Case",
        lead_examiner="Examiner 1",
    )
    service.create_case(dto)
    service.delete_case("2026-ARCHIVED-0001", purge=False)

    with pytest.raises(InvalidCaseStateError, match="Cannot update soft-deleted"):
        service.update_case("2026-ARCHIVED-0001", CaseUpdateDto(title="Illegal Edit"))


def test_sequence_generation_after_purge(service: CaseService) -> None:
    # Create 2 cases
    c1 = service.create_case(CaseCreateDto(title="Case 1", lead_examiner="Inv 1"))
    c2 = service.create_case(CaseCreateDto(title="Case 2", lead_examiner="Inv 2"))

    # Purge c1
    service.delete_case(c1.number, purge=True)

    # Creating c3 must generate a number higher than c2, never colliding with c2
    c3 = service.create_case(CaseCreateDto(title="Case 3", lead_examiner="Inv 3"))
    assert c3.number != c2.number
    c2_seq = int(c2.number.split("-")[-1])
    c3_seq = int(c3.number.split("-")[-1])
    assert c3_seq > c2_seq

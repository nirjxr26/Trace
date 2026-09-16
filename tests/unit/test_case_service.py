"""Unit tests for Case application service using in-memory database."""

from pathlib import Path

import pytest

from trace_core.cases.domain import CaseStatus
from trace_core.cases.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseResponseDto,
    CaseUpdateDto,
)
from trace_core.cases.service import (
    CaseNotFoundError,
    CaseService,
    DuplicateCaseNumberError,
    InvalidCaseStateError,
)

pytestmark = pytest.mark.unit


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

    closed = service.close_case(
        "2026-CLOSE-0001",
        reason="Completed successfully",
        closed_by="Special Agent Scully",
    )
    assert closed.status == CaseStatus.CLOSED
    assert closed.closed_at is not None
    assert closed.closure_reason == "Completed successfully"
    assert closed.closed_by == "Special Agent Scully"

    # Attempting to re-close already sealed case must raise InvalidCaseStateError
    with pytest.raises(InvalidCaseStateError, match="already permanently closed"):
        service.close_case("2026-CLOSE-0001", reason="Duplicate close")


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

    update_dto = CaseUpdateDto(title="Illegal Edit")
    with pytest.raises(InvalidCaseStateError, match="permanently sealed"):
        service.update_case("2026-SEALED-0001", update_dto)


def test_tracked_snapshot_and_changed_fields() -> None:
    """Verify the shared 5W1H snapshot used by service diffs and shell previews."""
    from trace_core.cases.domain import Case, changed_fields, tracked_snapshot

    case = Case(number="2026-SNP-0001", title="T", lead_examiner="E", tags=["A", "b "])
    snap = tracked_snapshot(case)
    assert snap["title"] == "T"
    assert snap["tags"] == ["a", "b"]
    assert changed_fields(snap, {**snap, "notes": "new"}) == ["notes"]
    assert changed_fields(snap, dict(snap)) == []


def test_cannot_update_deleted_case(service: CaseService) -> None:
    dto = CaseCreateDto(
        number="2026-ARCHIVED-0001",
        title="Archived Case",
        lead_examiner="Examiner 1",
    )
    service.create_case(dto)
    service.delete_case("2026-ARCHIVED-0001", purge=False)

    update_dto = CaseUpdateDto(title="Illegal Edit")
    with pytest.raises(InvalidCaseStateError, match="Cannot update soft-deleted"):
        service.update_case("2026-ARCHIVED-0001", update_dto)


def test_sequence_generation_after_purge(service: CaseService) -> None:
    # Create 2 cases
    c1 = service.create_case(CaseCreateDto(title="Case 1", lead_examiner="Inv 1"))
    c2 = service.create_case(CaseCreateDto(title="Case 2", lead_examiner="Inv 2"))

    # Soft delete and then purge c1
    service.delete_case(c1.number, purge=False)
    service.delete_case(c1.number, purge=True)

    # Creating c3 must generate a number higher than c2, never colliding with c2
    c3 = service.create_case(CaseCreateDto(title="Case 3", lead_examiner="Inv 3"))
    assert c3.number != c2.number
    c2_seq = int(c2.number.split("-")[-1])
    c3_seq = int(c3.number.split("-")[-1])
    assert c3_seq > c2_seq


def test_reusable_service_and_dto_hierarchy(service: CaseService) -> None:
    import uuid

    from trace_core.cases.repository import SqlAlchemyCaseRepository
    from trace_core.core.dto import BaseFilterDto, BaseResponseDto
    from trace_core.core.service import BaseService

    # 1. BaseService inheritance
    assert isinstance(service, BaseService)

    # 2. BaseResponseDto and BaseFilterDto inheritance
    case = service.create_case(CaseCreateDto(title="Hierarchy Test", lead_examiner="Inv 1"))
    assert isinstance(case, BaseResponseDto)
    assert isinstance(case.id, uuid.UUID)

    filter_dto = CaseFilterDto(search="Hierarchy")
    assert isinstance(filter_dto, BaseFilterDto)

    # 3. SqlAlchemyBaseRepository exists() and count()
    with service.session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        assert repo.exists(case.id) is True
        assert repo.exists(uuid.uuid4()) is False
        assert repo.count() >= 1


def test_sample_cases_batch_and_storage(
    service: CaseService,
    sample_cases_batch: list[CaseResponseDto],
    temp_storage: Path,
) -> None:
    assert len(sample_cases_batch) == 3
    assert temp_storage.is_dir()

    results = service.list_cases(CaseFilterDto(search="Malware"))
    assert len(results) == 1
    assert results[0].number == "2026-BATCH-0002"

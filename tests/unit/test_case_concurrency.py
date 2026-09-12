"""Unit tests for optimistic concurrency control and sequence allocation."""

from datetime import UTC, datetime

import pytest

from trace_core.cases.domain import Case
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.models import CaseSequenceModel
from trace_core.cases.repository import SqlAlchemyCaseRepository
from trace_core.cases.service import CaseService, DuplicateCaseNumberError
from trace_core.core.clock import reset_clock, set_clock
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import ConcurrencyConflictError

pytestmark = pytest.mark.unit


def test_optimistic_concurrency_conflict(session_manager: DatabaseSessionManager) -> None:
    """Test that modifying a case with a stale version raises ConcurrencyConflictError."""
    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        case = Case(
            number="2026-CR-0100",
            title="Initial Title",
            lead_examiner="Examiner A",
        )
        created = repo.create(case)
        session.commit()
        assert created.version == 1

    # Examiner 1 reads case (version 1)
    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        case1 = repo.get_by_number("2026-CR-0100")
        assert case1 is not None
        assert case1.version == 1

        # Examiner 2 reads case (version 1)
        case2 = repo.get_by_number("2026-CR-0100")
        assert case2 is not None

        # Examiner 1 updates case (version becomes 2)
        case1.title = "Examiner 1 Title"
        updated1 = repo.update(case1)
        session.commit()
        assert updated1.version == 2

    # Examiner 2 tries to update with stale case2 (version 1)
    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        case2.title = "Examiner 2 Stale Overwrite"
        with pytest.raises(ConcurrencyConflictError) as exc_info:
            repo.update(case2)
        assert exc_info.value.expected_version == 1
        assert exc_info.value.actual_version == 2


def test_concurrency_safe_sequence_allocation(session_manager: DatabaseSessionManager) -> None:
    """Test atomic sequence counter incrementation across calls."""
    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        num1 = repo.get_next_sequence_number(year=2026)
        session.commit()

    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        num2 = repo.get_next_sequence_number(year=2026)
        session.commit()

    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        num3 = repo.get_next_sequence_number(year=2026)
        session.commit()

    assert num1 == "2026-CR-0001"
    assert num2 == "2026-CR-0002"
    assert num3 == "2026-CR-0003"

    # Verify sequence table state
    with session_manager.session() as session:
        seq_record = session.get(CaseSequenceModel, 2026)
        assert seq_record is not None
        assert seq_record.last_sequence == 3


def test_first_sequence_row_race_handling(session_manager: DatabaseSessionManager) -> None:
    """Verify that when a concurrent transaction inserts the initial sequence row, it recovers gracefully."""
    # Pre-insert a sequence row for year 2045 simulating concurrent thread completing first
    with session_manager.session() as s1:
        s1.add(CaseSequenceModel(year=2045, last_sequence=5))
        s1.commit()

    # Now call get_next_sequence_number for 2045
    with session_manager.session() as s2:
        repo = SqlAlchemyCaseRepository(s2)
        next_num = repo.get_next_sequence_number(year=2045)
        s2.commit()

    assert next_num == "2045-CR-0006"


def test_narrow_integrity_error_translation(session_manager: DatabaseSessionManager) -> None:
    """Test that IntegrityError is only translated to DuplicateCaseNumberError on number collision."""
    service = CaseService(session_manager)
    dto1 = CaseCreateDto(number="2026-UNIQ-0001", title="Unique 1", lead_examiner="Inv")
    service.create_case(dto1)

    # Creating identical number must raise DuplicateCaseNumberError
    dto2 = CaseCreateDto(number="2026-UNIQ-0001", title="Unique 2", lead_examiner="Inv")
    with pytest.raises(DuplicateCaseNumberError):
        service.create_case(dto2)


class MockFrozenClock:
    def __init__(self, frozen_time: datetime) -> None:
        self.frozen_time = frozen_time

    def now(self) -> datetime:
        return self.frozen_time


def test_injectable_clock() -> None:
    """Test that injectable Clock abstraction controls generated timestamps."""
    fixed_time = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
    mock_clock = MockFrozenClock(fixed_time)

    set_clock(mock_clock)
    try:
        case = Case(number="2030-CR-0001", title="Future Case", lead_examiner="Time Traveler")
        assert case.opened_at == fixed_time
    finally:
        reset_clock()

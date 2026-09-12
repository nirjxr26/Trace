"""Unit tests for Case lifecycle state machine."""

import pytest

from trace_core.cases.domain import Case, CaseStatus, TransitionError, can_transition, transition_case

pytestmark = pytest.mark.unit


def test_valid_transitions() -> None:
    case = Case(number="2026-CR-0010", title="Test", lead_examiner="Inv")

    # OPEN -> UNDER_REVIEW
    transition_case(case, CaseStatus.UNDER_REVIEW)
    assert case.status == CaseStatus.UNDER_REVIEW

    # UNDER_REVIEW -> CLOSED
    transition_case(case, CaseStatus.CLOSED)
    assert case.status == CaseStatus.CLOSED
    assert case.closed_at is not None

    # CLOSED -> OPEN (reopened)
    transition_case(case, CaseStatus.OPEN)
    assert case.status == CaseStatus.OPEN
    assert case.closed_at is None

    # OPEN -> CLOSED -> ARCHIVED -> OPEN
    transition_case(case, CaseStatus.CLOSED)
    assert case.closed_at is not None
    transition_case(case, CaseStatus.ARCHIVED)
    assert case.status == CaseStatus.ARCHIVED
    transition_case(case, CaseStatus.OPEN)
    assert case.status == CaseStatus.OPEN
    assert case.closed_at is None


def test_invalid_transitions() -> None:
    case = Case(number="2026-CR-0011", title="Test", lead_examiner="Inv", status=CaseStatus.CLOSED)

    # CLOSED -> UNDER_REVIEW is illegal
    assert not can_transition(CaseStatus.CLOSED, CaseStatus.UNDER_REVIEW)
    with pytest.raises(TransitionError):
        transition_case(case, CaseStatus.UNDER_REVIEW)

from datetime import UTC, datetime

import pytest

from trace_core.cases.domain import Case, CaseStatus, TransitionError, can_transition, transition_case

pytestmark = pytest.mark.unit


def test_valid_transitions() -> None:
    case = Case(number="2026-CR-0010", title="Test", lead_examiner="Inv")

    # OPEN -> UNDER_REVIEW
    assert can_transition(CaseStatus.OPEN, CaseStatus.UNDER_REVIEW)
    transition_case(case, CaseStatus.UNDER_REVIEW)
    assert case.status == CaseStatus.UNDER_REVIEW

    # UNDER_REVIEW -> OPEN
    assert can_transition(CaseStatus.UNDER_REVIEW, CaseStatus.OPEN)
    transition_case(case, CaseStatus.OPEN)
    assert case.status == CaseStatus.OPEN

    # OPEN -> CLOSED (Permanently sealed with closure metadata)
    assert can_transition(CaseStatus.OPEN, CaseStatus.CLOSED)
    transition_case(case, CaseStatus.CLOSED, reason="Investigation completed", closed_by="Chief Inv")
    assert case.status == CaseStatus.CLOSED
    assert case.closed_at is not None
    assert case.closure_reason == "Investigation completed"
    assert case.closed_by == "Chief Inv"


def test_invalid_transitions() -> None:
    now = datetime.now(UTC)
    case = Case(
        number="2026-CR-0011",
        title="Test",
        lead_examiner="Inv",
        status=CaseStatus.CLOSED,
        closed_at=now,
    )

    # CLOSED -> OPEN is strictly forbidden (permanently sealed)
    assert not can_transition(CaseStatus.CLOSED, CaseStatus.OPEN)
    with pytest.raises(TransitionError) as exc_info:
        transition_case(case, CaseStatus.OPEN)
    assert "Illegal transition from CLOSED to OPEN" in str(exc_info.value)

    # CLOSED -> UNDER_REVIEW is strictly forbidden
    assert not can_transition(CaseStatus.CLOSED, CaseStatus.UNDER_REVIEW)
    with pytest.raises(TransitionError):
        transition_case(case, CaseStatus.UNDER_REVIEW)

    # Cannot instantiate CLOSED case without closed_at
    with pytest.raises(ValueError, match="A CLOSED case must have a closed_at timestamp"):
        Case(number="2026-CR-0012", title="Test", lead_examiner="Inv", status=CaseStatus.CLOSED, closed_at=None)

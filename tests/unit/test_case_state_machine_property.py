"""Property-like test for CLOSED never reopens."""

import pytest

from trace_core.cases.domain import Case, CaseStatus, TransitionError, can_transition, transition_case

pytestmark = pytest.mark.unit


def test_closed_never_reopens_property() -> None:
    for target in (CaseStatus.OPEN, CaseStatus.UNDER_REVIEW):
        assert not can_transition(CaseStatus.CLOSED, target)
        case = Case(number="2026-CR-9998", title="T", lead_examiner="Ex", status=CaseStatus.OPEN)
        transition_case(case, CaseStatus.CLOSED, reason="x")
        with pytest.raises(TransitionError):
            transition_case(case, target)

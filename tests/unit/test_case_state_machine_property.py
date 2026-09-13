"""Property-like test for CLOSED never reopens."""

import pytest

from trace_core.cases.domain import Case, CaseStatus, TransitionError, can_transition, transition_case
from trace_core.core.domain import InvariantViolationError

pytestmark = pytest.mark.unit


def test_closed_never_reopens_property() -> None:
    for start in [CaseStatus.OPEN, CaseStatus.UNDER_REVIEW, CaseStatus.CLOSED]:
        for target in [CaseStatus.OPEN, CaseStatus.UNDER_REVIEW, CaseStatus.CLOSED]:
            if start == CaseStatus.CLOSED and target != CaseStatus.CLOSED:
                assert not can_transition(start, target)
                # ensure closed_at set for CLOSED start
                if start == CaseStatus.CLOSED:
                    # already has closed_at via transition
                    c2 = Case(number="2026-CR-9998", title="T", lead_examiner="Ex", status=CaseStatus.OPEN)
                    transition_case(c2, CaseStatus.CLOSED, reason="x")
                    with pytest.raises(TransitionError):
                        transition_case(c2, target)
                else:
                    # start is OPEN/UNDER_REVIEW -> CLOSED is allowed, but after close, reopen must fail
                    if target == CaseStatus.CLOSED:
                        continue
                    with pytest.raises((TransitionError, InvariantViolationError)):
                        # try illegal
                        c3 = Case(number="2026-CR-9997", title="T", lead_examiner="Ex", status=start)
                        if start != CaseStatus.CLOSED:
                            transition_case(c3, CaseStatus.CLOSED, reason="x")
                            transition_case(c3, target)

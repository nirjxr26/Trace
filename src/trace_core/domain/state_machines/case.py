"""Case lifecycle state machine."""

from datetime import UTC, datetime

from trace_core.domain.models.case import Case, CaseStatus


class TransitionError(Exception):
    """Raised when an illegal case lifecycle state transition is attempted."""

    def __init__(self, current: CaseStatus, target: CaseStatus, reason: str = ""):
        message = f"Illegal transition from {current.value} to {target.value}"
        if reason:
            message += f": {reason}"
        super().__init__(message)
        self.current = current
        self.target = target
        self.reason = reason


# Valid transitions graph
_VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.OPEN: {CaseStatus.UNDER_REVIEW, CaseStatus.CLOSED, CaseStatus.ARCHIVED},
    CaseStatus.UNDER_REVIEW: {CaseStatus.OPEN, CaseStatus.CLOSED, CaseStatus.ARCHIVED},
    CaseStatus.CLOSED: {CaseStatus.OPEN, CaseStatus.ARCHIVED},  # Reopen or Archive
    CaseStatus.ARCHIVED: {CaseStatus.OPEN},  # Unarchive
}


def can_transition(current: CaseStatus, target: CaseStatus) -> bool:
    """Check if transition between statuses is allowed."""
    return target in _VALID_TRANSITIONS.get(current, set())


def transition_case(case: Case, target: CaseStatus, reason: str = "") -> Case:
    """
    Transition a Case entity to a new status.
    Mutates case status and timestamps, returns the mutated case.
    Raises TransitionError if transition is disallowed.
    """
    if case.status == target:
        return case

    if not can_transition(case.status, target):
        raise TransitionError(case.status, target, reason)

    now = datetime.now(UTC)

    if target == CaseStatus.CLOSED:
        case.status = CaseStatus.CLOSED
        case.closed_at = now
    elif target == CaseStatus.OPEN:
        case.closed_at = None
        case.status = CaseStatus.OPEN
    else:
        case.status = target

    case.updated_at = now

    return case

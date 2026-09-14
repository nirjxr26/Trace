"""Case domain entity, status enum, and lifecycle state machine."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from trace_core.core.domain import BaseEntity, InvariantViolationError, now_utc


class CaseStatus(StrEnum):
    """Lifecycle status of a forensic case."""

    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


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


_VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.OPEN: {CaseStatus.UNDER_REVIEW, CaseStatus.CLOSED},
    CaseStatus.UNDER_REVIEW: {CaseStatus.OPEN, CaseStatus.CLOSED},
    CaseStatus.CLOSED: set(),  # Permanently sealed: CLOSED cases cannot transition to any other status
}


def can_transition(current: CaseStatus, target: CaseStatus) -> bool:
    """Check if transition between statuses is allowed."""
    return target in _VALID_TRANSITIONS.get(current, set())


STATUS_FILTER_KEYWORDS = ("ALL", "ARCHIVED")


def is_archived_filter(raw: str | None) -> bool:
    """Check if a status filter string requests archived (soft-deleted) records."""
    return raw is not None and raw.upper() == "ARCHIVED"


def parse_status_value(raw: str | None) -> CaseStatus | None:
    """Parse CLI status filter. ALL/ARCHIVED/None/invalid map to None (no lifecycle filter)."""
    if not raw or raw.upper() in STATUS_FILTER_KEYWORDS:
        return None
    try:
        return CaseStatus(raw.upper())
    except ValueError:
        return None


def transition_case(
    case: "Case",
    target: CaseStatus,
    reason: str = "",
    closed_by: str = "",
) -> "Case":
    """
    Transition a Case entity to a new status.
    Mutates case status and timestamps, returns the mutated case.
    Raises TransitionError if transition is disallowed.
    """
    if case.status == target:
        return case

    if not can_transition(case.status, target):
        raise TransitionError(case.status, target, reason)

    now = now_utc()

    if target == CaseStatus.CLOSED:
        object.__setattr__(case, "closed_at", now)
        object.__setattr__(case, "closure_reason", reason.strip() if reason else None)
        object.__setattr__(case, "closed_by", closed_by.strip() if closed_by else None)
        case.status = CaseStatus.CLOSED
    elif target == CaseStatus.OPEN:
        object.__setattr__(case, "closed_at", None)
        object.__setattr__(case, "closure_reason", None)
        object.__setattr__(case, "closed_by", None)
        case.status = CaseStatus.OPEN
    else:
        case.status = target

    case.updated_at = now
    return case


class Case(BaseEntity):
    """Domain entity representing a forensic case."""

    number: str = Field(..., min_length=1, max_length=100, description="Unique human-readable case identifier")
    title: str = Field(..., min_length=1, max_length=255, description="Brief descriptive title")
    lead_examiner: str = Field(..., min_length=1, max_length=255, description="Primary investigator identifier/name")
    status: CaseStatus = Field(default=CaseStatus.OPEN)
    closed_at: datetime | None = None
    closed_by: str | None = None
    closure_reason: str | None = None
    description: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
    )

    def __setattr__(self, name: str, value: Any) -> None:
        """Enforce strict immutability for Case identity fields once assigned."""
        if name in ("id", "number") and hasattr(self, name):
            current = getattr(self, name, None)
            if current is not None and current != value:
                raise InvariantViolationError(f"Case {name} is strictly immutable once assigned.")
        super().__setattr__(name, value)

    @model_validator(mode="after")
    def validate_lifecycle_consistency(self) -> "Case":
        """Enforce domain invariants: OPEN cases must not have closure details; CLOSED cases must have closed_at."""
        if self.status == CaseStatus.OPEN:
            if self.closed_at is not None:
                raise InvariantViolationError("An OPEN case cannot have a closed_at timestamp.")
            if self.closure_reason is not None:
                raise InvariantViolationError("An OPEN case cannot have a closure_reason.")
            if self.closed_by is not None:
                raise InvariantViolationError("An OPEN case cannot have a closed_by examiner.")
        elif self.status == CaseStatus.CLOSED and self.closed_at is None:
            raise InvariantViolationError("A CLOSED case must have a closed_at timestamp.")
        return self

    @field_validator("closed_at")
    @classmethod
    def validate_closed_at_utc(cls, v: datetime | None) -> datetime | None:
        """Validate that closed_at is converted to canonical UTC if present."""
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise InvariantViolationError("All timestamps must be timezone-aware UTC.")
        return v.astimezone(UTC)

    @field_validator("number")
    @classmethod
    def validate_number(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise InvariantViolationError("Case number cannot be empty.")
        return stripped

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise InvariantViolationError("Case title cannot be empty.")
        return stripped

    @field_validator("lead_examiner")
    @classmethod
    def validate_examiner(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise InvariantViolationError("Lead examiner cannot be empty.")
        return stripped

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        """Strip whitespace, lowercase, discard empty tags, deduplicate, cap 50 tags ×50 chars."""
        cleaned: list[str] = []
        for tag in v:
            stripped = tag.strip().lower()
            if not stripped or stripped in cleaned:
                continue
            if len(stripped) > 50:
                raise InvariantViolationError("tag exceeds maximum length of 50 characters.")
            cleaned.append(stripped)
            if len(cleaned) > 50:
                raise InvariantViolationError("too many tags (max 50).")
        return cleaned

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 10000:
            raise InvariantViolationError("description exceeds maximum length of 10000 characters.")
        return v

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 50000:
            raise InvariantViolationError("notes exceeds maximum length of 50000 characters.")
        return v


CASE_TRACKED_FIELDS = ("title", "lead_examiner", "description", "notes", "tags")


def tracked_snapshot(case: Any) -> dict[str, Any]:
    """5W1H field snapshot shared by service diffs and shell previews. Single source.

    Accepts the domain entity or its response DTO (same field names, duck-typed) so the
    domain layer never imports DTOs.
    """
    return {k: (list(getattr(case, k)) if k == "tags" else getattr(case, k)) for k in CASE_TRACKED_FIELDS}


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Field names whose snapshot values differ. Single source for diff detection."""
    return [k for k in before if before[k] != after.get(k)]

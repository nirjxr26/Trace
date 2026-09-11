"""Case domain models and status enum."""

from datetime import datetime
from enum import StrEnum

from pydantic import ConfigDict, Field, field_validator, model_validator

from trace_core.domain.common import BaseEntity, InvariantViolationError


class CaseStatus(StrEnum):
    """Lifecycle status of a forensic case."""

    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class Case(BaseEntity):
    """Domain entity representing a forensic case."""

    number: str = Field(..., min_length=1, max_length=100, description="Unique human-readable case identifier")
    title: str = Field(..., min_length=1, max_length=255, description="Brief descriptive title")
    lead_examiner: str = Field(..., min_length=1, max_length=255, description="Primary investigator identifier/name")
    status: CaseStatus = Field(default=CaseStatus.OPEN)
    closed_at: datetime | None = None
    description: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
    )

    @model_validator(mode="after")
    def validate_lifecycle_consistency(self) -> "Case":
        """Enforce domain invariant: OPEN cases must not have closed_at set."""
        if self.status == CaseStatus.OPEN and self.closed_at is not None:
            raise InvariantViolationError("An OPEN case cannot have a closed_at timestamp.")
        return self

    @field_validator("closed_at")
    @classmethod
    def validate_closed_at_utc(cls, v: datetime | None) -> datetime | None:
        """Validate that closed_at is UTC if present."""
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise InvariantViolationError("All timestamps must be timezone-aware UTC.")
        return v

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
        """Strip whitespace, discard empty tags, and deduplicate."""
        cleaned: list[str] = []
        for tag in v:
            stripped = tag.strip()
            if stripped and stripped not in cleaned:
                cleaned.append(stripped)
        return cleaned

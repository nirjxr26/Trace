"""Data Transfer Objects (DTOs) for Case operations."""

from datetime import datetime

from pydantic import Field, field_validator

from trace_core.cases.domain import Case, CaseStatus
from trace_core.core.dto import BaseCreateDto, BaseFilterDto, BaseResponseDto, BaseUpdateDto


class CaseCreateDto(BaseCreateDto):
    """Input DTO for creating a new Case."""

    title: str = Field(..., min_length=1, max_length=255)
    lead_examiner: str = Field(..., min_length=1, max_length=255)
    number: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=10000)
    notes: str | None = Field(default=None, max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("tags")
    @classmethod
    def validate_tags_cap(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) > 50:
                raise ValueError("tag exceeds maximum length of 50 characters.")
        if len(v) > 50:
            raise ValueError("too many tags (max 50).")
        return v


class CaseUpdateDto(BaseUpdateDto):
    """Input DTO for updating mutable fields of an existing Case."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    lead_examiner: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    notes: str | None = Field(default=None, max_length=50000)
    tags: list[str] | None = None


class CaseResponseDto(BaseResponseDto):
    """Standard serialized DTO representation of a Case."""

    number: str
    title: str
    lead_examiner: str
    status: CaseStatus
    closed_at: datetime | None = None
    closed_by: str | None = None
    closure_reason: str | None = None
    archived_at: datetime | None = None
    archived_by: str | None = None
    version: int = 1
    description: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, case: Case) -> "CaseResponseDto":
        """Factory method to convert domain Case to DTO."""
        return cls(
            id=case.id,
            number=case.number,
            title=case.title,
            lead_examiner=case.lead_examiner,
            status=case.status,
            opened_at=case.opened_at,
            closed_at=case.closed_at,
            closed_by=case.closed_by,
            closure_reason=case.closure_reason,
            archived_at=case.archived_at,
            archived_by=case.archived_by,
            version=case.version,
            updated_at=case.updated_at,
            description=case.description,
            notes=case.notes,
            tags=case.tags,
            is_deleted=case.is_deleted,
        )


class CaseFilterDto(BaseFilterDto):
    """Query filters for listing cases."""

    status: CaseStatus | None = None
    recent: bool = False

    def with_recent(self) -> "CaseFilterDto":
        """Recent ordering keeps all filters; only order + page change. Single source."""
        return self.model_copy(update={"recent": True, "limit": 5, "offset": 0})


def parse_tags(value: str | None) -> list[str] | None:
    """Parse comma-separated tag string into stripped non-empty list. None stays None."""
    if value is None:
        return None
    return [t.strip() for t in value.split(",") if t.strip()]

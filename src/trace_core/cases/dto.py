"""Data Transfer Objects (DTOs) for Case operations."""

from datetime import datetime

from pydantic import Field

from trace_core.cases.domain import Case, CaseStatus
from trace_core.core.dto import BaseCreateDto, BaseFilterDto, BaseResponseDto, BaseUpdateDto


class CaseCreateDto(BaseCreateDto):
    """Input DTO for creating a new Case."""

    title: str = Field(..., min_length=1, max_length=255)
    lead_examiner: str = Field(..., min_length=1, max_length=255)
    number: str | None = Field(default=None, max_length=100)
    description: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class CaseUpdateDto(BaseUpdateDto):
    """Input DTO for updating mutable fields of an existing Case."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    lead_examiner: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class CaseResponseDto(BaseResponseDto):
    """Standard serialized DTO representation of a Case."""

    number: str
    title: str
    lead_examiner: str
    status: CaseStatus
    closed_at: datetime | None = None
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
            updated_at=case.updated_at,
            description=case.description,
            notes=case.notes,
            tags=case.tags,
            is_deleted=case.is_deleted,
        )


class CaseFilterDto(BaseFilterDto):
    """Query filters for listing cases."""

    status: CaseStatus | None = None

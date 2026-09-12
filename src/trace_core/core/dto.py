"""Base Data Transfer Object abstractions for request/response contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BaseDto(BaseModel):
    """Base DTO with strict field rules."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class BaseCreateDto(BaseDto):
    """Marker base for entity creation requests."""


class BaseUpdateDto(BaseDto):
    """Marker base for entity mutation requests."""


class BaseResponseDto(BaseDto):
    """Standardized response contract for all domain entities."""

    id: UUID
    opened_at: datetime
    updated_at: datetime
    is_deleted: bool = False


class BaseFilterDto(BaseDto):
    """Standardized pagination, search, and archival filters."""

    search: str | None = None
    include_deleted: bool = False
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

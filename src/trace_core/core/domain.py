"""Common domain foundations, value objects, and base entities."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def now_utc() -> datetime:
    """Return current timestamp in timezone-aware UTC."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime object is timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class DomainError(ValueError):
    """Base exception for all domain-level rule violations."""

    pass


class EntityNotFoundError(DomainError):
    """Raised when an entity cannot be found by its identifier."""

    def __init__(self, entity_name: str, identifier: Any):
        super().__init__(f"{entity_name} with identifier '{identifier}' was not found.")
        self.entity_name = entity_name
        self.identifier = identifier


class InvariantViolationError(DomainError):
    """Raised when a business invariant is violated."""

    pass


class BaseEntity(BaseModel):
    """Reusable base domain entity with identity and timestamps."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    opened_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    is_deleted: bool = Field(default=False)

    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
    )

    @field_validator("opened_at", "updated_at")
    @classmethod
    def validate_utc(cls, v: datetime | None) -> datetime | None:
        """Enforce timezone-aware UTC timestamps."""
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise InvariantViolationError("All timestamps must be timezone-aware UTC.")
        return v

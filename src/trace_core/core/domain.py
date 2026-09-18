"""Common domain foundations, value objects, and base entities."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trace_core.core.canonical import coerce_utc
from trace_core.core.clock import now_utc

_CONTROLS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_controls(value: str, multiline: bool = False) -> str:
    """Remove terminal control characters. Newlines survive only when multiline."""
    text = _CONTROLS_RE.sub("", value).replace("\r", "")
    return text if multiline else text.replace("\n", "")


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime object is timezone-aware UTC."""
    return coerce_utc(dt)


def require_utc(dt: datetime | None) -> datetime | None:
    """Reject naive timestamps, coerce aware to UTC. Single source for validators."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise InvariantViolationError("All timestamps must be timezone-aware UTC.")
    return dt.astimezone(UTC)


def parse_enum_value(enum_cls: Any, raw: str | None) -> Any:
    """Uppercase name lookup returning the member or None. Single source for enum flag parsing."""
    if not raw:
        return None
    try:
        return enum_cls(raw.upper())
    except ValueError:
        return None


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
    archived_at: datetime | None = Field(default=None)
    archived_by: str | None = Field(default=None, max_length=255)
    version: int = Field(default=1, ge=1)
    is_deleted: bool = Field(default=False)

    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
    )

    @field_validator("opened_at", "updated_at", "archived_at")
    @classmethod
    def validate_utc(cls, v: datetime | None) -> datetime | None:
        """Enforce timezone-aware UTC timestamps."""
        return require_utc(v)

"""Common domain foundations, value objects, and base entities."""

import re
import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trace_core.core.canonical import is_naive
from trace_core.core.clock import now_utc

__all__ = [
    "BaseEntity",
    "DomainError",
    "InvariantViolationError",
    "is_naive",
    "now_utc",
    "parse_enum_value",
    "require_utc",
    "strip_controls",
]

_CONTROLS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_controls(value: str, multiline: bool = False) -> str:
    """Remove terminal control characters. Newlines survive only when multiline."""
    text = _CONTROLS_RE.sub("", value).replace("\r", "")
    return text if multiline else text.replace("\n", "")


def require_utc(dt: datetime | None) -> datetime | None:
    """Reject naive timestamps, coerce aware to UTC. Single source for validators."""
    if dt is None:
        return None
    if is_naive(dt):
        raise InvariantViolationError("All timestamps must be timezone-aware UTC.")
    return dt.astimezone(UTC)


def parse_enum_value[EnumT: Enum](enum_cls: type[EnumT], raw: str | None) -> EnumT | None:
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

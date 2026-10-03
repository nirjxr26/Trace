"""SQLAlchemy 2.0 Base model and reusable schema mixins."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from trace_core.core.canonical import coerce_utc
from trace_core.core.clock import now_utc


class UTCDateTime(TypeDecorator[datetime]):
    """Timestamp column that is timezone-aware UTC on every backend.

    DateTime(timezone=True) is a no-op on SQLite: its result processor returns a
    naive datetime, so every read handed callers a value that looked UTC but was
    really local wall-clock — the 5h30m error in the field labelled UTC. Both
    directions run through coerce_utc, so what is stored and what comes back are
    aware UTC on SQLite and untouched on PostgreSQL. Naive input is rejected
    upstream by the domain layer's require_utc, not here: SQLAlchemy wraps bind
    errors in StatementError, which would land on the error-masking path.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        return coerce_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return coerce_utc(value)


class Base(DeclarativeBase):
    """Base declarative class for all Trace ORM models."""

    pass


class TimestampMixin:
    """Reusable mixin providing timezone-aware opened_at and updated_at columns."""

    opened_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        index=True,
        default=now_utc,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=now_utc,
        onupdate=now_utc,
        nullable=False,
    )


class SoftDeleteMixin:
    """Reusable mixin providing soft-delete functionality."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
    )

"""SQLAlchemy 2.0 Base model and reusable schema mixins."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from trace_core.core.clock import now_utc


class Base(DeclarativeBase):
    """Base declarative class for all Trace ORM models."""

    pass


class TimestampMixin:
    """Reusable mixin providing timezone-aware opened_at and updated_at columns."""

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: now_utc(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: now_utc(),
        onupdate=lambda: now_utc(),
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
        DateTime(timezone=True),
        nullable=True,
    )

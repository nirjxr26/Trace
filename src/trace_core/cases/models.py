"""SQLAlchemy 2.0 ORM Models for Cases."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trace_core.core.database.base import Base, SoftDeleteMixin, TimestampMixin


class CaseModel(Base, TimestampMixin, SoftDeleteMixin):
    """SQLAlchemy model for cases table."""

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    lead_examiner: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), index=True, default="OPEN", nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    closure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class CaseSequenceModel(Base):
    """Sequence allocation counter per calendar year for collision-free case numbering."""

    __tablename__ = "case_sequences"

    year: Mapped[int] = mapped_column(primary_key=True)
    last_sequence: Mapped[int] = mapped_column(default=0, nullable=False)

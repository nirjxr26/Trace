"""Audit SQLAlchemy models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trace_core.core.database.base import Base


class AuditChainStateModel(Base):
    """Single-row chain head for serializing global audit appends."""

    __tablename__ = "audit_chain_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    last_seq: Mapped[int] = mapped_column(default=0, nullable=False)
    last_chain_hash: Mapped[str] = mapped_column(String(64), default="0" * 64, nullable=False)


class AuditEventModel(Base):
    """Append-only audit ledger row."""

    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject_case_number: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    subject_case_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_chain: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)

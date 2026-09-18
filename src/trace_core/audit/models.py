"""Audit SQLAlchemy models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trace_core.core.clock import now_utc
from trace_core.core.database.base import Base


class AuditChainStateModel(Base):
    """Single-row chain head for serializing global audit appends."""

    __tablename__ = "audit_chain_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    last_seq: Mapped[int] = mapped_column(default=0, nullable=False)
    last_chain_hash: Mapped[str] = mapped_column(String(64), default="0" * 64, nullable=False)


INTENT_PENDING = "pending"
INTENT_CONFIRMED = "confirmed"
INTENT_FAILED = "failed"


class AnchorIntentModel(Base):
    """Durable anchor outbox. Written in-transaction; publisher confirms later."""

    __tablename__ = "anchor_intents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    case_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(nullable=False)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=INTENT_PENDING, nullable=False)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


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
    key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)

"""Device SQLAlchemy models: forensic observation history [D3]."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trace_core.core.clock import now_utc
from trace_core.core.database.base import Base, UTCDateTime
from trace_core.core.domain import MAX_ACTOR
from trace_core.devices.domain import MAX_DEVICE_STRING, MAX_NODE_LENGTH


class DeviceFingerprintModel(Base):
    """One observation of one device. Append-only; never upserted [D3].

    Deliberately no uniqueness constraint: a changed serial across two inspections
    is itself evidence, so rows accumulate and reads take the latest per identity.
    Retention is indefinite and independent of case purge [D29].
    """

    __tablename__ = "device_fingerprints"
    __table_args__ = (Index("ix_device_fingerprints_identity", "serial", "inspected_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    node: Mapped[str] = mapped_column(String(MAX_NODE_LENGTH), nullable=False)
    serial: Mapped[str] = mapped_column(String(MAX_DEVICE_STRING), nullable=False)
    model: Mapped[str] = mapped_column(String(MAX_DEVICE_STRING), nullable=False)
    capacity_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    firmware: Mapped[str | None] = mapped_column(String(MAX_DEVICE_STRING), nullable=True)
    interface: Mapped[str] = mapped_column(String(32), nullable=False)
    wwn: Mapped[str | None] = mapped_column(String(MAX_DEVICE_STRING), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unknown_cause: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc, nullable=False)
    inspected_by: Mapped[str] = mapped_column(String(MAX_ACTOR), nullable=False)

"""Device SQLAlchemy models: forensic observation history [D3]."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trace_core.core.clock import now_utc
from trace_core.core.database.base import Base, UTCDateTime
from trace_core.core.domain import MAX_ACTOR
from trace_core.devices.domain import MAX_DEVICE_STRING, MAX_NODE_LENGTH

MAX_CASE_NUMBER = 64


class DeviceFingerprintModel(Base):
    """One observation of one device. Append-only; never upserted [D3].

    Deliberately no uniqueness constraint: a changed serial across two inspections
    is itself evidence, so rows accumulate and reads take the latest per identity.
    Retention is indefinite and independent of case purge [D29].
    """

    __tablename__ = "device_fingerprints"
    __table_args__ = (
        Index("ix_device_fingerprints_identity", "serial", "inspected_at"),
        Index("ix_device_fingerprints_case_number", "case_number"),
        Index("ix_device_fingerprints_node", "node"),
        Index("ix_device_fingerprints_inspected_at", "inspected_at"),
    )

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
    case_number: Mapped[str | None] = mapped_column(String(MAX_CASE_NUMBER), nullable=True)


class CaseDeviceModel(Base):
    """One device filed under one case. Bookkeeping, not evidence.

    Attachment is its own act and its own row: it needs no device access, so it must not
    require an inspection. No foreign key to `cases` on purpose - a purge must never
    cascade into device records [D29], exactly as for observations.
    """

    __tablename__ = "case_devices"
    __table_args__ = (
        Index("ix_case_devices_case_number", "case_number"),
        Index("ix_case_devices_node", "node"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_number: Mapped[str] = mapped_column(String(MAX_CASE_NUMBER), nullable=False)
    node: Mapped[str] = mapped_column(String(MAX_NODE_LENGTH), nullable=False)
    serial: Mapped[str | None] = mapped_column(String(MAX_DEVICE_STRING), nullable=True)
    label: Mapped[str | None] = mapped_column(String(MAX_DEVICE_STRING), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc, nullable=False)
    linked_by: Mapped[str] = mapped_column(String(MAX_ACTOR), nullable=False)

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from trace_core.core.clock import now_utc
from trace_core.core.database.base import Base, UTCDateTime
from trace_core.imaging.domain import ImagingState


class ImagingOperationModel(Base):
    __tablename__ = "imaging_operations"
    __table_args__ = (
        Index("ix_imaging_operations_case_id", "case_id"),
        Index("ix_imaging_operations_case_number", "case_number"),
        Index("ix_imaging_operations_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_number: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=ImagingState.PREPARING.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc, nullable=True)
    source_node: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_serial: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_model: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_protection: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_adapter: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_inspected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expected_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    copied_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    acquisition_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    readback_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_relpath: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    manifest_relpath: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

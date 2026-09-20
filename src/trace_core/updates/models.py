import uuid
from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trace_core.core.database.base import Base
from trace_core.core.domain import now_utc


class UpdateHistoryModel(Base):
    __tablename__ = "update_history"
    __table_args__ = (Index("ix_update_history_started_at", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[str] = mapped_column(String(36), nullable=False)
    release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    from_version: Mapped[str] = mapped_column(String(32), nullable=False)
    to_version: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signing_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    migration_range: Mapped[str | None] = mapped_column(String(32), nullable=True)
    health_check_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    backup_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    restart_required: Mapped[bool] = mapped_column(default=False)
    rollback: Mapped[bool] = mapped_column(default=False)
    started_at: Mapped[datetime] = mapped_column(default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

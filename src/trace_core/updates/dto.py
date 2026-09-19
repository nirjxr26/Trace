from datetime import datetime
from uuid import UUID

from trace_core.core.dto import BaseDto


class UpdateHistoryCreateDto(BaseDto):
    from_version: str
    to_version: str
    started_at: datetime | None = None
    channel: str = "stable"
    result: str = "SUCCESS"
    artifact_sha256: str | None = None
    signing_key_id: str | None = None
    failure_reason: str | None = None
    failure_stage: str | None = None
    migration_range: str | None = None
    health_check_result: str | None = None
    backup_path: str | None = None
    override_reason: str | None = None
    restart_required: bool = False
    rollback: bool = False
    transaction_id: str | None = None
    release_id: str | None = None


class UpdateHistoryDto(BaseDto):
    id: UUID
    transaction_id: str
    release_id: str | None = None
    from_version: str
    to_version: str
    channel: str
    result: str
    rollback: bool = False
    migration_range: str | None = None
    health_check_result: str | None = None
    failure_stage: str | None = None
    backup_path: str | None = None
    override_reason: str | None = None
    started_at: datetime
    completed_at: datetime | None = None

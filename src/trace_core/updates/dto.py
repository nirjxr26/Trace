from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from trace_core.core.clock import now_utc
from trace_core.core.dto import BaseDto


class UpdateHistoryCreateDto(BaseDto):
    from_version: str
    to_version: str
    started_at: datetime = Field(default_factory=now_utc)
    channel: str = "stable"
    result: str = "SUCCESS"

    @field_validator("channel")
    @classmethod
    def _channel_known(cls, value: str) -> str:
        from trace_core.updates.domain import UpdateChannel

        if not UpdateChannel.contains(value):
            raise ValueError(f"unknown channel {value!r}")
        return value

    @field_validator("result")
    @classmethod
    def _result_known(cls, value: str) -> str:
        from trace_core.updates.domain import UpdateResult

        if value not in (UpdateResult.SUCCESS, UpdateResult.FAILED, UpdateResult.ROLLED_BACK):
            raise ValueError(f"unknown result {value!r}")
        return value

    @field_validator("failure_stage")
    @classmethod
    def _stage_known(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from trace_core.updates.domain import UpdateFailureStage, UpdateState

        allowed = {
            UpdateFailureStage.POLICY,
            UpdateFailureStage.STAGING,
            UpdateFailureStage.HEALTH,
            UpdateFailureStage.RECOVERY,
            UpdateFailureStage.MIGRATION,
        }
        states = {str(s).lower() for s in UpdateState}
        if value not in allowed and value.lower() not in states:
            raise ValueError(f"unknown failure_stage {value!r}")
        return value

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
    failure_reason: str | None = None
    failure_stage: str | None = None
    backup_path: str | None = None
    override_reason: str | None = None
    artifact_sha256: str | None = None
    signing_key_id: str | None = None
    restart_required: bool = False
    started_at: datetime
    completed_at: datetime | None = None

    @classmethod
    def from_model(cls, m: object) -> "UpdateHistoryDto":
        """Single source for model -> DTO mapping. Shared by record/list paths."""
        return cls(
            id=getattr(m, "id"),
            transaction_id=getattr(m, "transaction_id"),
            release_id=getattr(m, "release_id"),
            from_version=getattr(m, "from_version"),
            to_version=getattr(m, "to_version"),
            channel=getattr(m, "channel"),
            result=getattr(m, "result"),
            rollback=bool(getattr(m, "rollback", False)),
            migration_range=getattr(m, "migration_range"),
            health_check_result=getattr(m, "health_check_result"),
            failure_reason=getattr(m, "failure_reason"),
            failure_stage=getattr(m, "failure_stage"),
            backup_path=getattr(m, "backup_path"),
            override_reason=getattr(m, "override_reason"),
            artifact_sha256=getattr(m, "artifact_sha256"),
            signing_key_id=getattr(m, "signing_key_id"),
            restart_required=bool(getattr(m, "restart_required", False)),
            started_at=getattr(m, "started_at"),
            completed_at=getattr(m, "completed_at"),
        )

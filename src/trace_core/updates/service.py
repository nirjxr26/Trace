import uuid
from pathlib import Path

from sqlalchemy import select

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.domain import now_utc
from trace_core.core.service import BaseService
from trace_core.updates.dto import UpdateHistoryCreateDto, UpdateHistoryDto
from trace_core.updates.models import UpdateHistoryModel


class UpdateService(BaseService):
    def __init__(self, session_manager: DatabaseSessionManager | None = None):
        super().__init__(session_manager)

    def record_history(self, dto: UpdateHistoryCreateDto | dict) -> UpdateHistoryDto:
        if not isinstance(dto, UpdateHistoryCreateDto):
            dto = UpdateHistoryCreateDto.model_validate(dto)

        with self.transaction() as uow:
            tid = dto.transaction_id or str(uuid.uuid4())
            m = UpdateHistoryModel(
                id=uuid.uuid4(),
                transaction_id=tid,
                release_id=dto.release_id,
                from_version=dto.from_version,
                to_version=dto.to_version,
                channel=dto.channel,
                result=dto.result,
                artifact_sha256=dto.artifact_sha256,
                signing_key_id=dto.signing_key_id,
                failure_reason=dto.failure_reason,
                failure_stage=dto.failure_stage,
                migration_range=dto.migration_range,
                health_check_result=dto.health_check_result,
                backup_path=dto.backup_path,
                override_reason=dto.override_reason,
                restart_required=dto.restart_required,
                rollback=dto.rollback,
                started_at=dto.started_at or now_utc(),
                completed_at=now_utc(),
            )
            uow.session.add(m)
            from trace_core.updates.dto import UpdateHistoryDto as Dto

            return Dto(
                id=m.id,
                transaction_id=m.transaction_id,
                release_id=m.release_id,
                from_version=m.from_version,
                to_version=m.to_version,
                channel=m.channel,
                result=m.result,
                rollback=m.rollback,
                migration_range=m.migration_range,
                health_check_result=m.health_check_result,
                failure_stage=m.failure_stage,
                backup_path=m.backup_path,
                override_reason=m.override_reason,
                started_at=m.started_at,
                completed_at=m.completed_at,
            )

    def list_history(self, limit: int = 50, offset: int = 0) -> list[UpdateHistoryDto]:
        from trace_core.core.database.repository import paginate

        with self.session_manager.session() as session:
            q = paginate(select(UpdateHistoryModel).order_by(UpdateHistoryModel.started_at.desc()), limit, offset)
            rows = session.scalars(q).all()
            return [
                UpdateHistoryDto(
                    id=r.id,
                    transaction_id=r.transaction_id,
                    release_id=r.release_id,
                    from_version=r.from_version,
                    to_version=r.to_version,
                    channel=r.channel,
                    result=r.result,
                    rollback=r.rollback,
                    migration_range=r.migration_range,
                    health_check_result=r.health_check_result,
                    failure_stage=r.failure_stage,
                    backup_path=r.backup_path,
                    override_reason=r.override_reason,
                    started_at=r.started_at,
                    completed_at=r.completed_at,
                )
                for r in rows
            ]

    def write_result_marker(self, data: dict, path: str | Path | None = None) -> Path:
        from trace_core.updates.marker import write_marker

        return write_marker(data, path)

    def read_result_marker(self, path: str | Path | None = None) -> dict | None:
        import json

        from trace_core.core.settings import settings

        target = Path(path) if path else Path(settings.storage_root) / "update-result.json"
        if not target.exists():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

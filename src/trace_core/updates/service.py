import uuid
from pathlib import Path

from sqlalchemy import select

from trace_core.core.clock import now_utc
from trace_core.core.service import BaseService
from trace_core.updates.dto import UpdateHistoryCreateDto, UpdateHistoryDto
from trace_core.updates.models import UpdateHistoryModel


class UpdateService(BaseService):
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
                started_at=dto.started_at,
                completed_at=now_utc(),
            )
            uow.session.add(m)
            return UpdateHistoryDto.from_model(m)

    def list_history(self, limit: int = 50, offset: int = 0) -> list[UpdateHistoryDto]:
        from trace_core.core.database.repository import paginate
        from trace_core.core.errors import ValidationError

        if limit < 0 or offset < 0:
            raise ValidationError("limit and offset must be >= 0")
        with self.session_manager.session() as session:
            q = paginate(
                select(UpdateHistoryModel).order_by(UpdateHistoryModel.started_at.desc(), UpdateHistoryModel.id.desc()),
                limit,
                offset,
            )
            rows = session.scalars(q).all()
            return [UpdateHistoryDto.from_model(r) for r in rows]

    def write_result_marker(self, data: dict, path: str | Path | None = None) -> Path:
        from trace_core.updates.marker import write_marker

        return write_marker(data, path)

    def read_result_marker(self, path: str | Path | None = None) -> dict | None:
        from trace_core.updates.errors import RecoveryError
        from trace_core.updates.marker import marker_path, read_marker

        target = Path(path) if path else marker_path()
        if not target.exists():
            return None
        try:
            return read_marker(target)
        except RecoveryError:
            return None

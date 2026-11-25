from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from trace_core.core.clock import now_utc
from trace_core.imaging.domain import (
    BlockerMode,
    ImagingFailure,
    ImagingOperation,
    ImagingSource,
    ImagingState,
    require_transition,
)
from trace_core.imaging.models import ImagingOperationModel

_TERMINAL_STATES = (
    ImagingState.BYTE_VERIFIED.value,
    ImagingState.FAILED.value,
    ImagingState.QUARANTINED.value,
    ImagingState.INTERRUPTED.value,
)
_FAILURE_STATES = {ImagingState.INTERRUPTED, ImagingState.FAILED, ImagingState.QUARANTINED}


def _to_dto(model: ImagingOperationModel) -> ImagingOperation:
    return ImagingOperation.model_validate(model, from_attributes=True)


class SqlAlchemyImagingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def has_blocking_operation(self, case_id: UUID) -> bool:
        statement = select(ImagingOperationModel.id).where(
            ImagingOperationModel.case_id == case_id,
            ImagingOperationModel.state.not_in(_TERMINAL_STATES),
        )
        return self.session.scalar(statement.limit(1)) is not None

    def has_any_blocking_operation(self) -> bool:
        statement = select(ImagingOperationModel.id).where(ImagingOperationModel.state.not_in(_TERMINAL_STATES))
        return self.session.scalar(statement.limit(1)) is not None

    def create(self, case_id: UUID, case_number: str, actor: str) -> ImagingOperation:
        model = ImagingOperationModel(case_id=case_id, case_number=case_number, created_by=actor)
        self.session.add(model)
        self.session.flush()
        return _to_dto(model)

    def get(self, operation_id: UUID) -> ImagingOperation | None:
        model = self.session.get(ImagingOperationModel, operation_id)
        return _to_dto(model) if model is not None else None

    def list_for_case(self, case_number: str) -> list[ImagingOperation]:
        statement = (
            select(ImagingOperationModel)
            .where(ImagingOperationModel.case_number == case_number)
            .order_by(ImagingOperationModel.created_at.desc(), ImagingOperationModel.id.asc())
            .limit(100)
        )
        return [_to_dto(model) for model in self.session.scalars(statement)]

    def list_recent(self, limit: int = 100) -> list[ImagingOperation]:
        statement = (
            select(ImagingOperationModel)
            .order_by(ImagingOperationModel.created_at.desc(), ImagingOperationModel.id.asc())
            .limit(limit)
        )
        return [_to_dto(model) for model in self.session.scalars(statement)]

    def claim_for_acquisition(
        self,
        operation_id: UUID,
        source: ImagingSource,
        expected_bytes: int,
        image_relpath: str,
        manifest_relpath: str,
        started_at: datetime,
        blocker_mode: BlockerMode,
    ) -> ImagingOperation | None:
        model = self.session.get(ImagingOperationModel, operation_id)
        if model is None:
            return None
        require_transition(ImagingState(model.state), ImagingState.ACQUIRING)
        model.blocker_mode = blocker_mode.value
        model.source_node = source.node
        model.source_kind = source.kind.value
        model.source_serial = source.serial
        model.source_model = source.model
        model.source_size_bytes = source.size_bytes
        model.source_protection = source.protection
        model.source_adapter = source.adapter
        model.source_inspected_at = source.inspected_at
        model.expected_bytes = expected_bytes
        model.image_relpath = image_relpath
        model.manifest_relpath = manifest_relpath
        model.started_at = started_at
        model.updated_at = started_at
        model.state = ImagingState.ACQUIRING.value
        self.session.flush()
        return _to_dto(model)

    def resume_claim(self, operation_id: UUID, started_at: datetime) -> ImagingOperation | None:
        model = self.session.get(ImagingOperationModel, operation_id)
        if model is None:
            return None
        require_transition(ImagingState(model.state), ImagingState.ACQUIRING)
        model.state = ImagingState.ACQUIRING.value
        model.failure_category = None
        model.started_at = started_at
        model.updated_at = started_at
        self.session.flush()
        return _to_dto(model)

    def mark_verifying(self, operation_id: UUID, copied_bytes: int, acquisition_sha256: str) -> ImagingOperation | None:
        model = self.session.get(ImagingOperationModel, operation_id)
        if model is None:
            return None
        require_transition(ImagingState(model.state), ImagingState.VERIFYING)
        model.copied_bytes = copied_bytes
        model.acquisition_sha256 = acquisition_sha256
        model.updated_at = now_utc()
        model.state = ImagingState.VERIFYING.value
        self.session.flush()
        return _to_dto(model)

    def mark_verified(
        self,
        operation_id: UUID,
        readback_bytes: int,
        readback_sha256: str,
        finished_at: datetime,
    ) -> ImagingOperation | None:
        model = self.session.get(ImagingOperationModel, operation_id)
        if model is None:
            return None
        require_transition(
            ImagingState(model.state),
            ImagingState.BYTE_VERIFIED,
            expected_bytes=model.expected_bytes,
            copied_bytes=model.copied_bytes,
            readback_bytes=readback_bytes,
            acquisition_sha256=model.acquisition_sha256,
            readback_sha256=readback_sha256,
        )
        model.readback_sha256 = readback_sha256
        model.finished_at = finished_at
        model.updated_at = finished_at
        model.state = ImagingState.BYTE_VERIFIED.value
        self.session.flush()
        return _to_dto(model)

    def mark_failure(
        self,
        operation_id: UUID,
        target: ImagingState,
        failure: ImagingFailure,
        finished_at: datetime,
    ) -> ImagingOperation | None:
        if target not in _FAILURE_STATES:
            raise ValueError("Only an interrupted, failed, or quarantined state can record a failure.")
        model = self.session.get(ImagingOperationModel, operation_id)
        if model is None:
            return None
        require_transition(ImagingState(model.state), target)
        model.failure_category = failure.value
        model.finished_at = finished_at
        model.updated_at = finished_at
        model.state = target.value
        self.session.flush()
        return _to_dto(model)

    def abandon(self, operation_id: UUID) -> ImagingOperation | None:
        model = self.session.get(ImagingOperationModel, operation_id)
        if model is None:
            return None
        current = ImagingState(model.state)
        if current is ImagingState.PREPARING:
            failure = None
        elif current in {ImagingState.ACQUIRING, ImagingState.VERIFYING, ImagingState.INTERRUPTED}:
            failure = ImagingFailure.INTERRUPTED
        else:
            raise ValueError("Only an unresolved operation can be abandoned.")
        require_transition(current, ImagingState.FAILED)
        finished_at = now_utc()
        if failure is not None:
            model.failure_category = failure.value
        model.state = ImagingState.FAILED.value
        model.finished_at = finished_at
        model.updated_at = finished_at
        self.session.flush()
        return _to_dto(model)

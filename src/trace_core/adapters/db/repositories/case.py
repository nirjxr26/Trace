"""SQLAlchemy Case repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from trace_core.adapters.db.models import CaseModel
from trace_core.adapters.db.repositories.base import SqlAlchemyBaseRepository
from trace_core.domain.common import ensure_utc
from trace_core.domain.models.case import Case, CaseStatus
from trace_core.ports.repositories.case import CaseRepository


class SqlAlchemyCaseRepository(SqlAlchemyBaseRepository[CaseModel, Case, uuid.UUID], CaseRepository):
    """Case persistence repository extending generic CRUD."""

    def __init__(self, session: Session):
        super().__init__(session=session, model_cls=CaseModel)

    def _to_domain(self, model: CaseModel) -> Case:
        return Case(
            id=model.id,
            number=model.number,
            title=model.title,
            lead_examiner=model.lead_examiner,
            status=CaseStatus(model.status),
            opened_at=ensure_utc(model.opened_at) or datetime.now(UTC),
            closed_at=ensure_utc(model.closed_at),
            updated_at=ensure_utc(model.updated_at) or datetime.now(UTC),
            description=model.description,
            notes=model.notes,
            tags=list(model.tags or []),
            is_deleted=model.is_deleted,
        )

    def _to_model(self, case: Case) -> CaseModel:
        return CaseModel(
            id=case.id,
            number=case.number,
            title=case.title,
            lead_examiner=case.lead_examiner,
            status=case.status.value,
            opened_at=case.opened_at,
            closed_at=case.closed_at,
            updated_at=case.updated_at,
            description=case.description,
            notes=case.notes,
            tags=case.tags,
            is_deleted=case.is_deleted,
        )

    def _update_model(self, model: CaseModel, entity: Case) -> None:
        model.title = entity.title
        model.lead_examiner = entity.lead_examiner
        model.status = entity.status.value
        model.description = entity.description
        model.notes = entity.notes
        model.tags = entity.tags
        model.closed_at = entity.closed_at
        model.is_deleted = entity.is_deleted

    def get_by_number(self, number: str) -> Case | None:
        """Fetch a case by human-readable case number."""
        stmt = select(CaseModel).where(CaseModel.number == number.strip())
        model = self.session.scalar(stmt)
        return self._to_domain(model) if model else None

    def resolve(self, identifier: str) -> Case | None:
        """Dual-key lookup: resolve by UUID or by case number."""
        identifier = identifier.strip()
        try:
            val_uuid = uuid.UUID(identifier)
            case = self.get_by_id(val_uuid)
            if case:
                return case
        except ValueError:
            pass
        return self.get_by_number(identifier)

    def list_cases(
        self,
        status: CaseStatus | None = None,
        search: str | None = None,
        include_deleted: bool = False,
    ) -> list[Case]:
        """List cases with search and status filters."""
        stmt = select(CaseModel)

        if not include_deleted:
            stmt = stmt.where(CaseModel.is_deleted.is_(False))

        if status is not None:
            stmt = stmt.where(CaseModel.status == status.value)

        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    CaseModel.number.ilike(pattern),
                    CaseModel.title.ilike(pattern),
                    CaseModel.lead_examiner.ilike(pattern),
                    CaseModel.description.ilike(pattern),
                )
            )

        stmt = stmt.order_by(CaseModel.opened_at.desc())
        models = self.session.scalars(stmt).all()
        return [self._to_domain(m) for m in models]

    def soft_delete(self, case_id: uuid.UUID) -> bool:
        """Mark a case as archived/deleted."""
        stmt = select(CaseModel).where(CaseModel.id == case_id)
        model = self.session.scalar(stmt)
        if not model:
            return False

        model.is_deleted = True
        model.status = CaseStatus.ARCHIVED.value
        model.updated_at = datetime.now(UTC)
        self.session.flush()
        return True

    def purge(self, case_id: uuid.UUID) -> bool:
        """Permanently delete a case record."""
        return super().delete(case_id, purge=True)

    def delete(self, entity_id: uuid.UUID, purge: bool = False) -> bool:
        """Delete case entity. If not purge, delegate to soft_delete."""
        if purge:
            return self.purge(entity_id)
        return self.soft_delete(entity_id)

    def get_next_sequence_number(self, year: int | None = None) -> str:
        """Generate next sequential case number for the year, e.g. '2026-CR-0001'."""
        current_year = year or datetime.now(UTC).year
        prefix = f"{current_year}-CR-"

        stmt = select(CaseModel.number).where(CaseModel.number.startswith(prefix)).order_by(CaseModel.number.desc())
        existing_numbers = self.session.scalars(stmt).all()

        max_seq = 0
        for num in existing_numbers:
            suffix = num[len(prefix) :]
            if suffix.isdigit():
                max_seq = max(max_seq, int(suffix))

        return f"{prefix}{max_seq + 1:04d}"

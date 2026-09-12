"""Case repository port interface and SQLAlchemy adapter implementation."""

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from trace_core.cases.domain import Case, CaseStatus
from trace_core.cases.models import CaseModel, CaseSequenceModel
from trace_core.core.database.repository import SqlAlchemyBaseRepository
from trace_core.core.domain import ensure_utc, now_utc
from trace_core.core.errors import ConcurrencyConflictError


class CaseRepository(Protocol):
    """Port defining persistence contracts for Case entities."""

    def create(self, entity: Case) -> Case: ...
    def get_by_id(self, entity_id: uuid.UUID) -> Case | None: ...
    def get_by_number(self, number: str) -> Case | None: ...
    def resolve(self, identifier: str) -> Case | None: ...
    def list_cases(
        self,
        status: CaseStatus | None = None,
        search: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Case]: ...
    def update(self, entity: Case) -> Case: ...
    def delete(self, entity_id: uuid.UUID, purge: bool = False) -> bool: ...
    def soft_delete(self, case_id: uuid.UUID) -> bool: ...
    def purge(self, case_id: uuid.UUID) -> bool: ...
    def get_next_sequence_number(self, year: int | None = None) -> str: ...
    def exists(self, entity_id: uuid.UUID) -> bool: ...
    def count(self, include_deleted: bool = False) -> int: ...


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
            closed_by=model.closed_by,
            closure_reason=model.closure_reason,
            archived_at=ensure_utc(model.archived_at),
            version=model.version,
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
            closed_by=case.closed_by,
            closure_reason=case.closure_reason,
            archived_at=case.archived_at,
            version=case.version,
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
        model.closed_by = entity.closed_by
        model.closure_reason = entity.closure_reason
        model.archived_at = entity.archived_at
        model.version = entity.version
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
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Case]:
        """List cases with search, status filters, deterministic sorting, and pagination."""
        stmt = select(CaseModel)

        if not include_deleted:
            stmt = stmt.where(CaseModel.is_deleted.is_(False))

        if status is not None:
            stmt = stmt.where(CaseModel.status == status.value)

        normalized_search = search.strip() if search and search.strip() else None
        if normalized_search:
            pattern = f"%{normalized_search}%"
            stmt = stmt.where(
                or_(
                    CaseModel.number.ilike(pattern),
                    CaseModel.title.ilike(pattern),
                    CaseModel.lead_examiner.ilike(pattern),
                    CaseModel.description.ilike(pattern),
                    CaseModel.notes.ilike(pattern),
                )
            )

        stmt = stmt.order_by(CaseModel.opened_at.desc(), CaseModel.id.asc())

        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        models = self.session.scalars(stmt).all()
        return [self._to_domain(m) for m in models]

    def soft_delete(self, case_id: uuid.UUID) -> bool:
        """Mark a case as archived/deleted without corrupting investigation status."""
        stmt = select(CaseModel).where(CaseModel.id == case_id)
        model = self.session.scalar(stmt)
        if not model:
            return False

        model.is_deleted = True
        model.archived_at = datetime.now(UTC)
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

    def update(self, entity: Case) -> Case:
        """Update case entity with optimistic concurrency checking."""
        stmt = select(CaseModel).where(CaseModel.id == entity.id)
        model = self.session.scalar(stmt)
        if not model:
            raise ValueError(f"Case with id {entity.id} does not exist.")

        if model.version != entity.version:
            raise ConcurrencyConflictError(
                resource_type="Case",
                identifier=entity.number,
                expected_version=entity.version,
                actual_version=model.version,
            )

        self._update_model(model, entity)
        model.version += 1
        model.updated_at = now_utc()
        self.session.flush()
        return self._to_domain(model)

    def get_next_sequence_number(self, year: int | None = None) -> str:
        """Atomically allocate the next sequential case number for the year (e.g. '2026-CR-0001')."""
        current_year = year or now_utc().year
        prefix = f"{current_year}-CR-"

        stmt = select(CaseSequenceModel).where(CaseSequenceModel.year == current_year).with_for_update()
        seq_record = self.session.scalar(stmt)

        if seq_record is None:
            stmt_cases = select(CaseModel.number).where(CaseModel.number.startswith(prefix))
            existing_numbers = self.session.scalars(stmt_cases).all()
            max_seq = 0
            for num in existing_numbers:
                suffix = num[len(prefix) :]
                if suffix.isdigit():
                    max_seq = max(max_seq, int(suffix))
            seq_record = CaseSequenceModel(year=current_year, last_sequence=max_seq)
            self.session.add(seq_record)

        seq_record.last_sequence += 1
        self.session.flush()
        return f"{prefix}{seq_record.last_sequence:04d}"

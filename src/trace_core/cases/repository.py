"""Case repository port interface and SQLAlchemy adapter implementation."""

import uuid
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trace_core.cases.domain import Case, CaseStatus, normalize_number
from trace_core.cases.models import CaseModel, CaseSequenceModel, PurgedNumberModel
from trace_core.core.canonical import parse_trailing_seq
from trace_core.core.clock import now_utc
from trace_core.core.database.repository import SqlAlchemyBaseRepository, ilike_literal, paginate
from trace_core.core.domain import ensure_utc


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
        recent: bool = False,
        deleted_only: bool = False,
    ) -> list[Case]: ...
    def update(self, entity: Case) -> Case: ...
    def delete(self, entity_id: uuid.UUID, purge: bool = False) -> bool: ...
    def soft_delete(self, case_id: uuid.UUID, expected_version: int, archived_by: str | None = None) -> bool: ...
    def restore(self, case_id: uuid.UUID, expected_version: int) -> bool: ...
    def purge(self, case_id: uuid.UUID, expected_version: int) -> bool: ...
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
            opened_at=ensure_utc(model.opened_at) or now_utc(),
            closed_at=ensure_utc(model.closed_at),
            closed_by=model.closed_by,
            closure_reason=model.closure_reason,
            archived_at=ensure_utc(model.archived_at),
            archived_by=model.archived_by,
            version=model.version,
            updated_at=ensure_utc(model.updated_at) or now_utc(),
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
            archived_by=case.archived_by,
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
        model.archived_by = entity.archived_by
        model.version = entity.version
        model.is_deleted = entity.is_deleted

    def get_by_number(self, number: str) -> Case | None:
        """Fetch a case by human-readable case number."""
        stmt = select(CaseModel).where(CaseModel.number == normalize_number(number))
        model = self.session.scalar(stmt)
        return self._to_domain(model) if model else None

    def is_purged(self, number: str) -> bool:
        """Check the tombstone without hydrating. Single source for create/allocator guards."""
        return self.session.get(PurgedNumberModel, normalize_number(number)) is not None

    def record_purge(self, number: str) -> None:
        """Tombstone a purged number in the same transaction. Never re-register."""
        self.session.add(PurgedNumberModel(number=normalize_number(number)))
        self.session.flush()

    def note_manual_number(self, number: str) -> None:
        """Advance the year counter past a high manual number so autos never collide."""
        parts = normalize_number(number).split("-")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[2].isdigit():
            return
        row = self.session.scalar(select(CaseSequenceModel).where(CaseSequenceModel.year == int(parts[0])))
        if row is not None and int(parts[2]) > row.last_sequence:
            row.last_sequence = int(parts[2])
            self.session.flush()

    def resolve(self, identifier: str) -> Case | None:
        """Dual-key lookup: resolve by UUID or by canonical case number."""
        identifier = normalize_number(identifier)
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
        recent: bool = False,
        deleted_only: bool = False,
    ) -> list[Case]:
        """List cases with search, status filters, deterministic sorting, and pagination."""
        stmt = select(CaseModel)

        if deleted_only:
            stmt = stmt.where(CaseModel.is_deleted.is_(True))
        elif not include_deleted:
            stmt = stmt.where(CaseModel.is_deleted.is_(False))

        if status is not None:
            stmt = stmt.where(CaseModel.status == status.value)

        normalized_search = search.strip() if search and search.strip() else None
        if normalized_search:
            stmt = stmt.where(
                or_(
                    ilike_literal(CaseModel.number, normalized_search),
                    ilike_literal(CaseModel.title, normalized_search),
                    ilike_literal(CaseModel.lead_examiner, normalized_search),
                    ilike_literal(CaseModel.description, normalized_search),
                    ilike_literal(CaseModel.notes, normalized_search),
                )
            )

        if recent:
            stmt = stmt.order_by(CaseModel.updated_at.desc(), CaseModel.id.asc())
        else:
            stmt = stmt.order_by(CaseModel.opened_at.desc(), CaseModel.id.asc())

        stmt = paginate(stmt, limit, offset)

        models = self.session.scalars(stmt).all()
        return [self._to_domain(m) for m in models]

    def soft_delete(self, case_id: uuid.UUID, expected_version: int, archived_by: str | None = None) -> bool:
        """Mark a case as archived/deleted without corrupting investigation status."""
        model = self._fetch(case_id)
        if not model:
            return False

        self._guard_version(model, expected_version, "Case", str(model.number))

        model.is_deleted = True
        model.archived_at = now_utc()
        model.archived_by = archived_by
        model.version += 1
        model.updated_at = now_utc()
        self.session.flush()
        return True

    def restore(self, case_id: uuid.UUID, expected_version: int) -> bool:
        """Restore an archived case back to active retention."""
        model = self._fetch(case_id)
        if not model:
            return False

        self._guard_version(model, expected_version, "Case", str(model.number))

        model.is_deleted = False
        model.archived_at = None
        model.archived_by = None
        model.version += 1
        model.updated_at = now_utc()
        self.session.flush()
        return True

    def purge(self, case_id: uuid.UUID, expected_version: int) -> bool:
        """Permanently delete a case record."""
        model = self._fetch(case_id)
        if not model:
            return False

        self._guard_version(model, expected_version, "Case", str(model.number))

        purged_number = str(model.number)
        self.session.delete(model)
        self.session.flush()
        self.record_purge(purged_number)
        return True

    def delete(self, entity_id: uuid.UUID, purge: bool = False, expected_version: int | None = None) -> bool:  # type: ignore[override]
        """Delete case entity. Forensic path requires OCC version."""
        if expected_version is None:
            raise ValueError("expected_version is required for forensic delete")
        if purge:
            return self.purge(entity_id, expected_version=expected_version)
        return self.soft_delete(entity_id, expected_version=expected_version)

    def update(self, entity: Case) -> Case:
        """Update case entity with optimistic concurrency checking."""
        model = self._fetch(entity.id)
        if not model:
            raise ValueError(f"Case with id {entity.id} does not exist.")

        self._guard_version(model, entity.version, "Case", entity.number)

        self._update_model(model, entity)
        model.version += 1
        model.updated_at = now_utc()
        self.session.flush()
        return self._to_domain(model)

    def _scan_max_seq(self, current_year: int) -> int:
        """Max trailing seq among existing numbers of the year. Cold-start helper."""
        stmt_cases = select(CaseModel.number).where(CaseModel.number.startswith(f"{current_year}-"))
        existing_numbers = self.session.scalars(stmt_cases).all()
        max_seq = 0
        for num in existing_numbers:
            seq = parse_trailing_seq(num)
            if seq is not None:
                max_seq = max(max_seq, seq)
        return max_seq

    def _ensure_seq_record(self, current_year: int, seq_record: CaseSequenceModel | None) -> CaseSequenceModel:
        """Return locked sequence row, creating it on cold start with race recovery."""
        if seq_record is not None:
            return seq_record
        max_seq = self._scan_max_seq(current_year)
        try:
            with self.session.begin_nested():
                new_seq = CaseSequenceModel(year=current_year, last_sequence=max_seq)
                self.session.add(new_seq)
                self.session.flush()
            return new_seq
        except IntegrityError:
            # Concurrent transaction inserted the initial sequence row for this year; re-query with row lock
            stmt = select(CaseSequenceModel).where(CaseSequenceModel.year == current_year).with_for_update()
            seq_record = self.session.scalar(stmt)
            if seq_record is None:
                raise
            return seq_record

    def _is_candidate_free(self, candidate: str) -> bool:
        """Candidate unused and not tombstoned. Single source for allocator guard."""
        return self.get_by_number(candidate) is None and not self.is_purged(candidate)

    def get_next_sequence_number(self, year: int | None = None) -> str:
        """Atomically allocate the next sequential case number for the year (e.g. '2026-CR-0001')."""
        current_year = year or now_utc().year
        prefix = f"{current_year}-CR-"

        stmt = select(CaseSequenceModel).where(CaseSequenceModel.year == current_year).with_for_update()
        seq_record = self._ensure_seq_record(current_year, self.session.scalar(stmt))

        for _ in range(10000):
            seq_record.last_sequence += 1
            self.session.flush()
            candidate = f"{prefix}{seq_record.last_sequence:04d}"
            if self._is_candidate_free(candidate):
                return candidate
        raise ValueError(f"Case sequence exhausted for year {current_year} (check for manual number crowding).")

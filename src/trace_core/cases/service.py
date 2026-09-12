"""Case application service managing Case lifecycle, numbering, and transactions."""

import uuid

from sqlalchemy.exc import IntegrityError

from trace_core.cases.domain import Case, CaseStatus, TransitionError, transition_case
from trace_core.cases.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseResponseDto,
    CaseUpdateDto,
)
from trace_core.cases.repository import SqlAlchemyCaseRepository
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import (
    ApplicationError,
    ConflictError,
    NotFoundError,
    StateTransitionError,
)
from trace_core.core.service import BaseService


class CaseError(ApplicationError):
    """Base exception for Case application service errors."""

    pass


class CaseNotFoundError(NotFoundError, CaseError):
    """Raised when a case cannot be found by ID or number."""

    def __init__(self, identifier: str):
        super().__init__(resource_type="Case", identifier=identifier)


class DuplicateCaseNumberError(ConflictError, CaseError):
    """Raised when attempting to create a case with an existing number."""

    def __init__(self, number: str):
        super().__init__(resource_type="Case", field="number", value=number)
        self.number = number


class InvalidCaseStateError(StateTransitionError, CaseError):
    """Raised when an operation violates case lifecycle state constraints."""

    def __init__(self, message: str):
        super().__init__(current_state="UNKNOWN", target_state="UNKNOWN", reason=message)


def _resolve_actor(actor: str | None, fallback: str = "system") -> str:
    """Resolve audit actor, defaulting to fallback examiner or system."""
    cleaned = actor.strip() if actor else ""
    return cleaned or fallback.strip() or "system"


def _require_case(repo: SqlAlchemyCaseRepository, identifier: str) -> Case:
    """Resolve case by number/UUID or raise not-found. Shared by all service actions."""
    case = repo.resolve(identifier)
    if not case:
        raise CaseNotFoundError(identifier)
    return case


class CaseService(BaseService):
    """Application service for managing Case lifecycle and queries."""

    def __init__(self, session_manager: DatabaseSessionManager | None = None):
        super().__init__(session_manager)

    def create_case(self, dto: CaseCreateDto, actor: str | None = None) -> CaseResponseDto:
        """Create and persist a new forensic case."""
        _ = _resolve_actor(actor, dto.lead_examiner)
        with self.transaction() as uow:
            repo = SqlAlchemyCaseRepository(uow.session)

            case_number = dto.number.strip() if dto.number else repo.get_next_sequence_number()

            # Check duplicate case number upfront
            existing = repo.get_by_number(case_number)
            if existing:
                raise DuplicateCaseNumberError(case_number)

            case_entity = Case(
                id=uuid.uuid4(),
                number=case_number,
                title=dto.title,
                lead_examiner=dto.lead_examiner,
                description=dto.description,
                notes=dto.notes,
                tags=dto.tags,
                status=CaseStatus.OPEN,
            )

            try:
                created = repo.create(case_entity)
                return CaseResponseDto.from_domain(created)
            except IntegrityError as e:
                err_msg = str(e).lower()
                if "number" in err_msg or "uq_cases_number" in err_msg:
                    raise DuplicateCaseNumberError(case_number) from e
                raise ApplicationError(f"Database constraint violation: {e}") from e

    def get_case(self, identifier: str) -> CaseResponseDto:
        """Retrieve a case by UUID or Case Number."""
        with self.session_manager.session() as session:
            repo = SqlAlchemyCaseRepository(session)
            return CaseResponseDto.from_domain(_require_case(repo, identifier))

    def list_cases(self, filter_dto: CaseFilterDto | None = None) -> list[CaseResponseDto]:
        """List cases according to filter criteria."""
        query_filter = filter_dto or CaseFilterDto()
        with self.session_manager.session() as session:
            repo = SqlAlchemyCaseRepository(session)
            cases = repo.list_cases(
                status=query_filter.status,
                search=query_filter.search,
                include_deleted=query_filter.include_deleted,
                limit=query_filter.limit,
                offset=query_filter.offset,
            )
            return [CaseResponseDto.from_domain(c) for c in cases]

    def update_case(self, identifier: str, dto: CaseUpdateDto, actor: str | None = None) -> CaseResponseDto:
        """Update mutable fields of an existing case."""
        _ = _resolve_actor(actor, "system")
        with self.transaction() as uow:
            repo = SqlAlchemyCaseRepository(uow.session)
            case = _require_case(repo, identifier)

            if case.is_deleted:
                raise InvalidCaseStateError(f"Cannot update soft-deleted or archived case '{identifier}'.")

            if case.status == CaseStatus.CLOSED:
                raise InvalidCaseStateError(
                    f"Cannot update closed case '{identifier}'. Reopen the case before making changes."
                )

            # Update mutable fields
            if dto.title is not None:
                case.title = dto.title
            if dto.lead_examiner is not None:
                case.lead_examiner = dto.lead_examiner
            if dto.description is not None:
                case.description = dto.description
            if dto.notes is not None:
                case.notes = dto.notes
            if dto.tags is not None:
                case.tags = dto.tags

            updated = repo.update(case)
            return CaseResponseDto.from_domain(updated)

    def close_case(
        self, identifier: str, reason: str = "", closed_by: str = "", actor: str | None = None
    ) -> CaseResponseDto:
        """Transition case to permanently sealed CLOSED state."""
        with self.transaction() as uow:
            repo = SqlAlchemyCaseRepository(uow.session)
            case = _require_case(repo, identifier)

            if case.is_deleted:
                raise InvalidCaseStateError(f"Cannot close soft-deleted or archived case '{identifier}'.")

            if case.status == CaseStatus.CLOSED:
                raise InvalidCaseStateError(f"Case '{identifier}' is already permanently closed.")

            examiner = closed_by.strip() or _resolve_actor(actor, case.lead_examiner)
            try:
                transition_case(case, CaseStatus.CLOSED, reason=reason, closed_by=examiner)
            except TransitionError as e:
                raise InvalidCaseStateError(str(e)) from e

            updated = repo.update(case)
            return CaseResponseDto.from_domain(updated)

    def delete_case(self, identifier: str, purge: bool = False, actor: str | None = None) -> bool:
        """
        Delete a case.
        Default: soft-delete (archive).
        purge=True: permanently remove row from database.
        """
        resolved_actor = _resolve_actor(actor, "system")
        with self.transaction() as uow:
            repo = SqlAlchemyCaseRepository(uow.session)
            case = _require_case(repo, identifier)

            if not purge and case.is_deleted:
                raise InvalidCaseStateError(f"Case '{identifier}' is already archived/deleted.")

            if purge:
                if not case.is_deleted:
                    raise InvalidCaseStateError(
                        f"Forensic safety violation: Case '{identifier}' must be archived before it can be purged."
                    )
                return repo.purge(case.id)
            return repo.soft_delete(case.id, archived_by=resolved_actor)

    def restore_case(self, identifier: str, actor: str | None = None) -> CaseResponseDto:
        """Restore an archived case back to active retention."""
        _ = _resolve_actor(actor, "system")
        with self.transaction() as uow:
            repo = SqlAlchemyCaseRepository(uow.session)
            case = _require_case(repo, identifier)

            if not case.is_deleted:
                raise InvalidCaseStateError(f"Case '{identifier}' is not archived.")

            repo.restore(case.id)
            restored = repo.resolve(identifier)
            if not restored:
                raise CaseNotFoundError(identifier)
            return CaseResponseDto.from_domain(restored)

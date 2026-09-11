"""Case application service."""

import uuid

from sqlalchemy.exc import IntegrityError

from trace_core.adapters.db.repositories.case import SqlAlchemyCaseRepository
from trace_core.adapters.db.session import DatabaseSessionManager, db_manager
from trace_core.application.common.errors import (
    ApplicationError,
    ConflictError,
    NotFoundError,
    StateTransitionError,
)
from trace_core.application.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseResponseDto,
    CaseUpdateDto,
)
from trace_core.domain.models.case import Case, CaseStatus
from trace_core.domain.state_machines.case import TransitionError, transition_case


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
        super().__init__(f"Case number '{number}' already exists.")
        self.number = number


class InvalidCaseStateError(StateTransitionError, CaseError):
    """Raised when an operation violates case lifecycle state constraints."""

    pass


class CaseService:
    """Application service for managing Case lifecycle and queries."""

    def __init__(self, session_manager: DatabaseSessionManager | None = None):
        self.session_manager = session_manager or db_manager

    def create_case(self, dto: CaseCreateDto) -> CaseResponseDto:
        """Create and persist a new forensic case."""
        with self.session_manager.session() as session:
            repo = SqlAlchemyCaseRepository(session)

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
                session.commit()
                return CaseResponseDto.from_domain(created)
            except IntegrityError:
                session.rollback()
                raise DuplicateCaseNumberError(case_number)

    def get_case(self, identifier: str) -> CaseResponseDto:
        """Retrieve a case by UUID or Case Number."""
        with self.session_manager.session() as session:
            repo = SqlAlchemyCaseRepository(session)
            case = repo.resolve(identifier)
            if not case:
                raise CaseNotFoundError(identifier)
            return CaseResponseDto.from_domain(case)

    def list_cases(self, filter_dto: CaseFilterDto | None = None) -> list[CaseResponseDto]:
        """List cases according to filter criteria."""
        query_filter = filter_dto or CaseFilterDto()
        with self.session_manager.session() as session:
            repo = SqlAlchemyCaseRepository(session)
            cases = repo.list_cases(
                status=query_filter.status,
                search=query_filter.search,
                include_deleted=query_filter.include_deleted,
            )
            return [CaseResponseDto.from_domain(c) for c in cases]

    def update_case(self, identifier: str, dto: CaseUpdateDto) -> CaseResponseDto:
        """Update mutable fields of an existing case."""
        with self.session_manager.session() as session:
            repo = SqlAlchemyCaseRepository(session)
            case = repo.resolve(identifier)
            if not case:
                raise CaseNotFoundError(identifier)

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
            session.commit()
            return CaseResponseDto.from_domain(updated)

    def close_case(self, identifier: str, reason: str = "") -> CaseResponseDto:
        """Transition case from OPEN to CLOSED."""
        with self.session_manager.session() as session:
            repo = SqlAlchemyCaseRepository(session)
            case = repo.resolve(identifier)
            if not case:
                raise CaseNotFoundError(identifier)

            if case.is_deleted:
                raise InvalidCaseStateError(f"Cannot close soft-deleted or archived case '{identifier}'.")

            try:
                transition_case(case, CaseStatus.CLOSED, reason=reason)
            except TransitionError as e:
                raise InvalidCaseStateError(str(e)) from e

            updated = repo.update(case)
            session.commit()
            return CaseResponseDto.from_domain(updated)

    def delete_case(self, identifier: str, purge: bool = False) -> bool:
        """
        Delete a case.
        Default: soft-delete (archive).
        purge=True: permanently remove row from database.
        """
        with self.session_manager.session() as session:
            repo = SqlAlchemyCaseRepository(session)
            case = repo.resolve(identifier)
            if not case:
                raise CaseNotFoundError(identifier)

            if not purge and case.is_deleted:
                raise InvalidCaseStateError(f"Case '{identifier}' is already archived/deleted.")

            if purge:
                success = repo.purge(case.id)
            else:
                success = repo.soft_delete(case.id)

            session.commit()
            return success

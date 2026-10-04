"""Case application service managing Case lifecycle, numbering, and transactions."""

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError, OperationalError

from trace_core.cases.domain import (
    Case,
    CaseStatus,
    TransitionError,
    normalise_optional,
    tracked_snapshot,
    transition_case,
)
from trace_core.cases.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseResponseDto,
    CaseUpdateDto,
)
from trace_core.cases.repository import SqlAlchemyCaseRepository
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.domain import InvariantViolationError, strip_controls
from trace_core.core.errors import (
    ApplicationError,
    ConflictError,
    NotFoundError,
    StateTransitionError,
    ValidationError,
)
from trace_core.core.operators import require_admin, require_mutator
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


class CaseSequenceContentionError(ConflictError, CaseError):
    """Raised when year-sequence allocation loses the write lock to a concurrent transaction."""

    def __init__(self, message: str):
        super().__init__(resource_type="Case sequence", field="allocation", value=message)
        self.message = message


_NUMBER_UNIQUE_MARKERS = ("uq_cases_number", "unique constraint failed: cases.number")


class InvalidCaseStateError(StateTransitionError, CaseError):
    """Raised when an operation violates case lifecycle state constraints."""

    def __init__(self, message: str):
        super().__init__(current_state="", target_state="", reason=message)


def _resolve_actor(actor: str | None, fallback: str = "system") -> str:
    """Resolve audit actor, defaulting to fallback examiner or system."""
    cleaned = strip_controls(actor).strip() if actor else ""
    return cleaned or strip_controls(fallback).strip() or "system"


def _require_case(repo: SqlAlchemyCaseRepository, identifier: str) -> Case:
    """Resolve case by number/UUID or raise not-found. Shared by all service actions."""
    case = repo.resolve(identifier)
    if not case:
        raise CaseNotFoundError(identifier)
    return case


def _record_audit(  # type: ignore[no-untyped-def]
    session: Any,
    builder_tuple: tuple[Any, Any, dict[str, Any], Any],
    actor: str,
    claimed: str | None = None,
):
    from trace_core.audit.service import AuditService
    from trace_core.core.operators import current_identity

    action, subject, details, ctx = builder_tuple
    actual, _ = current_identity()
    if claimed and claimed.strip() and claimed.strip() != actual:
        details = {**details, "claimed_actor": claimed.strip()}
    return AuditService().record(session, action, subject, actor, details, ctx)


def _audit_hook(
    build: Callable[[], tuple[Any, Any, dict[str, Any], Any]],
    actor: str,
    claimed: str | None = None,
) -> Callable[[Any], None]:
    """before_commit hook recording one builder payload. Single source for the case mutations."""

    def _hook(session: Any) -> None:
        _record_audit(session, build(), actor, claimed=claimed)

    return _hook


class CaseService(BaseService):
    """Application service for managing Case lifecycle and queries."""

    def __init__(self, session_manager: DatabaseSessionManager | None = None):
        super().__init__(session_manager)

    def create_case(self, dto: CaseCreateDto, actor: str | None = None) -> CaseResponseDto:
        """Create and persist a new forensic case."""
        resolved_actor = _resolve_actor(actor, dto.lead_examiner)
        with self.transaction() as uow:
            require_mutator(uow.session, action="create cases")
            repo = SqlAlchemyCaseRepository(uow.session)

            try:
                # Allocation locks the year row, so it contends. It sat outside this
                # handler, which leaked a raw IntegrityError on the savepoint race and
                # SQLite's "database is locked" OperationalError to the caller.
                case_number = dto.number.strip() if dto.number else repo.get_next_sequence_number()

                # Check duplicate case number upfront; tombstoned numbers stay reserved
                if repo.get_by_number(case_number) or repo.is_purged(case_number):
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

                created = repo.create(case_entity)
                if dto.number:
                    repo.note_manual_number(case_number)

                from trace_core.audit.builder import for_case_created

                uow.before_commit(
                    _audit_hook(
                        lambda: for_case_created(
                            created.number,
                            created.id,
                            created.title,
                            created.lead_examiner,
                            number_source="manual" if dto.number else "auto",
                        ),
                        resolved_actor,
                        claimed=actor,
                    )
                )
                return CaseResponseDto.from_domain(created)
            except IntegrityError as e:
                err_msg = str(e).lower()
                if any(marker in err_msg for marker in _NUMBER_UNIQUE_MARKERS):
                    raise DuplicateCaseNumberError(case_number) from e
                raise ApplicationError(f"Database constraint violation: {e}") from e
            except OperationalError as e:
                # Narrow: only SQLite's write-lock contention maps to a transient error.
                # A blanket OperationalError catch would relabel real bugs as contention.
                if "locked" not in str(e).lower():
                    raise ApplicationError(f"Database unavailable: {e}") from e
                raise CaseSequenceContentionError("Case number allocation is contended; retry.") from e

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
                recent=query_filter.recent,
                deleted_only=query_filter.deleted_only,
            )
            return [CaseResponseDto.from_domain(c) for c in cases]

    def update_case(
        self, identifier: str, dto: CaseUpdateDto, actor: str | None = None, reason: str = ""
    ) -> CaseResponseDto:
        """Update mutable fields of an existing case."""
        with self.transaction() as uow:
            require_mutator(uow.session, action="update cases")
            repo = SqlAlchemyCaseRepository(uow.session)
            case = _require_case(repo, identifier)
            resolved_actor = _resolve_actor(actor, case.lead_examiner)

            if case.is_deleted:
                raise InvalidCaseStateError(f"Cannot update soft-deleted or archived case '{identifier}'.")

            if case.status == CaseStatus.CLOSED:
                raise InvalidCaseStateError(
                    f"Cannot update closed case '{identifier}'. Closed cases are permanently sealed."
                )

            # snapshot before for 5W1H diff
            before = tracked_snapshot(case)
            changed: list[str] = []
            if dto.title is not None and dto.title != case.title:
                changed.append("title")
                case.title = dto.title
            if dto.lead_examiner is not None and dto.lead_examiner != case.lead_examiner:
                changed.append("lead_examiner")
                case.lead_examiner = dto.lead_examiner
            # None and "" both mean "empty": comparing (and storing) the
            # normalized form keeps no-op edits from minting audit noise.
            if dto.description is not None and normalise_optional(dto.description) != normalise_optional(
                case.description
            ):
                changed.append("description")
                case.description = normalise_optional(dto.description)
            if dto.notes is not None and normalise_optional(dto.notes) != normalise_optional(case.notes):
                changed.append("notes")
                case.notes = normalise_optional(dto.notes)
            if dto.tags is not None:
                # The domain lowercases tags on validation; comparing the raw DTO list
                # against the normalised entity value minted phantom "tags" diffs
                # (e.g. --tags USB on a case holding usb) with before == after.
                normalised_tags = sorted({t.strip().lower() for t in dto.tags if t.strip()})
                if normalised_tags != sorted(set(case.tags)):
                    changed.append("tags")
                    case.tags = list(normalised_tags)

            if not changed:
                return CaseResponseDto.from_domain(case)

            after = tracked_snapshot(case)
            updated = repo.update(case)

            from trace_core.audit.builder import for_case_updated

            uow.before_commit(
                _audit_hook(
                    lambda: for_case_updated(updated.number, updated.id, changed, before, after, reason=reason),
                    resolved_actor,
                    claimed=actor,
                )
            )
            return CaseResponseDto.from_domain(updated)

    def close_case(
        self, identifier: str, reason: str = "", closed_by: str = "", actor: str | None = None
    ) -> CaseResponseDto:
        """Transition case to permanently sealed CLOSED state."""
        if not reason.strip():
            raise ValidationError("A closure reason is required to permanently seal a case.")
        with self.transaction() as uow:
            require_mutator(uow.session, action="close cases")
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

            pinned: dict[str, Any] = {}

            from trace_core.audit.builder import for_case_closed

            def _audit(s: Any) -> None:
                dto = _record_audit(
                    s,
                    for_case_closed(updated.number, updated.id, updated.closure_reason or "", examiner),
                    examiner,
                    claimed=closed_by or actor,
                )
                if dto is None or dto.seq is None:
                    raise InvariantViolationError("close audit hook produced no ledger position; refusing to seal")
                pinned["seq"], pinned["chain"] = dto.seq, dto.chain_hash

            def _intent(s: Any) -> None:
                # Exact seq/chain of THIS close, captured in-transaction. Never re-read head.
                from trace_core.audit.anchor import record_anchor_intent

                if not pinned:
                    raise InvariantViolationError("close anchor hook has no ledger position; refusing to seal")
                record_anchor_intent(s, updated.number, updated.id, pinned["seq"], pinned["chain"])

            def _publish() -> None:
                try:
                    from trace_core.audit.anchor import publish_pending_anchors

                    publish_pending_anchors(self.session_manager)
                except Exception as exc:
                    import structlog

                    structlog.get_logger().warning("Anchor publish failed", case=updated.number, error=str(exc))

            uow.before_commit(_audit)
            uow.before_commit(_intent)
            uow.on_commit(_publish)
            return CaseResponseDto.from_domain(updated)

    def delete_case(self, identifier: str, purge: bool = False, actor: str | None = None) -> bool:
        """
        Delete a case.
        Default: soft-delete (archive).
        purge=True: permanently remove row from database.
        """
        with self.transaction() as uow:
            require_mutator(uow.session, action="archive cases")
            repo = SqlAlchemyCaseRepository(uow.session)
            case = _require_case(repo, identifier)
            resolved_actor = _resolve_actor(actor, case.lead_examiner)

            if not purge and case.is_deleted:
                raise InvalidCaseStateError(f"Case '{identifier}' is already archived/deleted.")

            if purge:
                require_admin(uow.session, action="purge cases")
                if not case.is_deleted:
                    raise InvalidCaseStateError(
                        f"Forensic safety violation: Case '{identifier}' must be archived before it can be purged."
                    )
                purged_number = case.number
                purged_id = case.id
                result = repo.purge(case.id, expected_version=case.version)

                from trace_core.audit.builder import for_case_purged

                uow.before_commit(
                    _audit_hook(
                        lambda: for_case_purged(purged_number, purged_id),
                        resolved_actor,
                        claimed=actor,
                    )
                )
                return result
            result = repo.soft_delete(case.id, expected_version=case.version, archived_by=resolved_actor)

            from trace_core.audit.builder import for_case_archived

            uow.before_commit(
                _audit_hook(
                    lambda: for_case_archived(case.number, case.id),
                    resolved_actor,
                    claimed=actor,
                )
            )
            return result

    def restore_case(self, identifier: str, actor: str | None = None) -> CaseResponseDto:
        """Restore an archived case back to active retention."""
        with self.transaction() as uow:
            require_mutator(uow.session, action="restore cases")
            repo = SqlAlchemyCaseRepository(uow.session)
            case = _require_case(repo, identifier)
            resolved_actor = _resolve_actor(actor, case.lead_examiner)

            if not case.is_deleted:
                raise InvalidCaseStateError(f"Case '{identifier}' is not archived.")

            repo.restore(case.id, expected_version=case.version)
            restored = repo.get_by_id(case.id)
            if not restored:
                raise CaseNotFoundError(identifier)

            from trace_core.audit.builder import for_case_restored

            uow.before_commit(
                _audit_hook(
                    lambda: for_case_restored(restored.number, restored.id),
                    resolved_actor,
                    claimed=actor,
                )
            )
            return CaseResponseDto.from_domain(restored)

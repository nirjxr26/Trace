"""Tests for query engine, pagination, notes search, deterministic ordering, and purge guardrail."""

import pytest

from trace_core.cases.dto import CaseCreateDto, CaseFilterDto
from trace_core.cases.service import CaseService, InvalidCaseStateError
from trace_core.core.cli.error_handler import _resolve_error_details


def test_list_cases_pagination(service: CaseService) -> None:
    """Verify limit and offset pagination in CaseService.list_cases."""
    # Create 5 distinct cases
    for i in range(1, 6):
        service.create_case(
            CaseCreateDto(
                number=f"2026-PAG-{i:04d}",
                title=f"Pagination Case {i}",
                lead_examiner="Examiner P",
            )
        )

    # Page 1: limit 2, offset 0
    p1 = service.list_cases(CaseFilterDto(limit=2, offset=0))
    assert len(p1) == 2

    # Page 2: limit 2, offset 2
    p2 = service.list_cases(CaseFilterDto(limit=2, offset=2))
    assert len(p2) == 2

    # Ensure no overlap between page 1 and page 2
    p1_numbers = {c.number for c in p1}
    p2_numbers = {c.number for c in p2}
    assert p1_numbers.isdisjoint(p2_numbers)

    # Page 3: limit 2, offset 4
    p3 = service.list_cases(CaseFilterDto(limit=2, offset=4))
    assert len(p3) >= 1


def test_search_includes_notes(service: CaseService) -> None:
    """Verify searching finds matches within case notes."""
    service.create_case(
        CaseCreateDto(
            number="2026-NOTE-0001",
            title="Generic Investigation",
            lead_examiner="Examiner Notes",
            notes="Extracted secret cryptographic payload from hidden sector",
        )
    )

    # Search for a term only present in notes
    results = service.list_cases(CaseFilterDto(search="cryptographic payload"))
    assert len(results) >= 1
    assert any(c.number == "2026-NOTE-0001" for c in results)


def test_search_case_insensitive(service: CaseService) -> None:
    """Verify search matches across case on every backend (parity row 3)."""
    service.create_case(CaseCreateDto(number="2026-CASE-0001", title="MixedCaseTitle", lead_examiner="Examiner Ci"))
    assert any(c.number == "2026-CASE-0001" for c in service.list_cases(CaseFilterDto(search="mixedcasetitle")))
    assert any(c.number == "2026-CASE-0001" for c in service.list_cases(CaseFilterDto(search="MIXEDCASETITLE")))


def test_search_whitespace_normalization(service: CaseService) -> None:
    """Verify whitespace-only search string is normalized to None and returns cases."""
    service.create_case(
        CaseCreateDto(
            number="2026-NORM-0001",
            title="Normalized Search Test",
            lead_examiner="Examiner Norm",
        )
    )

    # Whitespace only should not fail or produce an invalid query
    results = service.list_cases(CaseFilterDto(search="    "))
    assert len(results) >= 1


def test_the_repository_refuses_to_reopen_a_sealed_case(session_manager, service: CaseService) -> None:
    """[§14.3] sealed closure holds at the repository, not only in the service and domain.

    A caller can hold an entity the domain would never build; the repository must not be
    a way around the invariant it persists.
    """
    from trace_core.cases.domain import Case, CaseStatus, TransitionError
    from trace_core.cases.repository import SqlAlchemyCaseRepository

    created = service.create_case(CaseCreateDto(title="Sealed", lead_examiner="Ex"))
    service.close_case(created.number, reason="Sealed for the record")
    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        stored = repo.get_by_number(created.number)
        assert stored is not None and stored.status is CaseStatus.CLOSED
        reopened = Case(
            id=stored.id,
            number=stored.number,
            title=stored.title,
            lead_examiner=stored.lead_examiner,
            status=CaseStatus.OPEN,
            version=stored.version,
        )
        with pytest.raises(TransitionError, match="permanently sealed"):
            repo.update(reopened)
        session.rollback()
    assert service.get_case(created.number).status == CaseStatus.CLOSED


def test_the_case_repository_port_matches_its_implementation() -> None:
    """The Protocol omitted `expected_version`, so calling through it always raised ValueError."""
    import inspect as py_inspect

    from trace_core.cases.repository import CaseRepository, SqlAlchemyCaseRepository

    declared = py_inspect.signature(CaseRepository.delete)
    actual = py_inspect.signature(SqlAlchemyCaseRepository.delete)
    assert list(declared.parameters) == list(actual.parameters), (declared, actual)


def test_no_generic_repository_can_hard_delete_a_row() -> None:
    """The generic `delete` discarded its own `purge` flag and the append-only device repo inherited it.

    Structural, not behavioural: the guard is the method's absence, because a test that
    re-adds the method and calls it would only prove the method works.
    """
    from trace_core.core.database.repository import SqlAlchemyBaseRepository
    from trace_core.devices.repository import SqlAlchemyDeviceRepository

    assert "delete" not in dir(SqlAlchemyBaseRepository)
    assert "delete" not in dir(SqlAlchemyDeviceRepository), "append-only rows must have no delete path at all"
    assert not hasattr(SqlAlchemyDeviceRepository, "purge")
    assert not hasattr(SqlAlchemyDeviceRepository, "soft_delete"), "observations are never archived"


def test_a_sealed_case_still_accepts_a_closure_metadata_correction(session_manager, service: CaseService) -> None:
    """The guard seals the status only; a closed case is otherwise still editable."""
    from trace_core.cases.domain import CaseStatus
    from trace_core.cases.repository import SqlAlchemyCaseRepository

    created = service.create_case(CaseCreateDto(title="Sealed", lead_examiner="Ex"))
    service.close_case(created.number, reason="first reason")
    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        stored = repo.get_by_number(created.number)
        assert stored is not None
        stored.notes = "corrected during review"
        saved = repo.update(stored)
        assert saved.status is CaseStatus.CLOSED
        session.rollback()


def test_purge_policy_guardrail_prevents_active_case_destruction(service: CaseService) -> None:
    """Verify attempting to permanently purge an active case without archiving raises an error."""
    service.create_case(
        CaseCreateDto(
            number="2026-GUARD-0001",
            title="Active Case Protected",
            lead_examiner="Guard Examiner",
        )
    )

    # Active case purge attempt must be blocked
    with pytest.raises(InvalidCaseStateError, match="must be archived before it can be purged"):
        service.delete_case("2026-GUARD-0001", purge=True)

    # After soft-deleting (archiving), purge is permitted
    service.delete_case("2026-GUARD-0001", purge=False)
    assert service.delete_case("2026-GUARD-0001", purge=True) is True


def test_error_sanitization_for_unexpected_exceptions() -> None:
    """Verify non-ApplicationError exceptions are sanitized when debug is False."""
    from trace_core.core.settings import settings

    orig_debug = settings.debug
    try:
        settings.debug = False
        raw_exc = RuntimeError("psycopg.OperationalError: password authentication failed for user 'postgres'")
        title, message, remediation, code = _resolve_error_details(raw_exc, None, None)
        assert "password" not in message
        assert "unexpected operational error" in message.lower()

        # In debug mode, raw technical details are retained
        settings.debug = True
        title, message, remediation, code = _resolve_error_details(raw_exc, None, None)
        assert "password authentication failed" in message
    finally:
        settings.debug = orig_debug


def test_archived_filter_shows_only_deleted(service: CaseService) -> None:
    """Verify deleted_only filter returns archived cases and hides actives."""
    service.create_case(CaseCreateDto(number="2026-ARC-0001", title="Active One", lead_examiner="Examiner A"))
    service.create_case(CaseCreateDto(number="2026-ARC-0002", title="Archived One", lead_examiner="Examiner A"))
    service.delete_case("2026-ARC-0002", purge=False)

    archived = service.list_cases(CaseFilterDto(deleted_only=True))
    numbers = {c.number for c in archived}
    assert "2026-ARC-0002" in numbers
    assert "2026-ARC-0001" not in numbers


def test_delete_actor_falls_back_to_lead_examiner(service: CaseService) -> None:
    """Verify archive audit attributes the lead examiner instead of system."""
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService

    service.create_case(CaseCreateDto(number="2026-ACT-0001", title="Actor Check", lead_examiner="Lead Who"))
    service.delete_case("2026-ACT-0001", purge=False)

    events = AuditService(service.session_manager).list_events(AuditFilterDto(case_number="2026-ACT-0001"))
    archived = [e for e in events if e.action.value == "CASE_ARCHIVED"]
    assert len(archived) == 1
    assert archived[0].actor == "Lead Who"


def test_dto_input_size_limits() -> None:
    """Verify description and notes enforce maximum length limits."""
    from pydantic import ValidationError

    # Exceeding description max length (10,000)
    with pytest.raises(ValidationError):
        CaseCreateDto(
            title="Valid Title",
            lead_examiner="Examiner Valid",
            description="A" * 10001,
        )

    # Exceeding notes max length (50,000)
    with pytest.raises(ValidationError):
        CaseCreateDto(
            title="Valid Title",
            lead_examiner="Examiner Valid",
            notes="N" * 50001,
        )

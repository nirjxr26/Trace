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

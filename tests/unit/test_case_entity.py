"""Unit tests for Case domain entity."""

from datetime import UTC, datetime

import pytest

from trace_core.cases.domain import Case, CaseStatus

pytestmark = pytest.mark.unit


def test_case_creation_valid() -> None:
    case = Case(
        number="2026-CR-0001",
        title="Test Case",
        lead_examiner="Investigator X",
        tags=["usb", "test"],
    )
    assert case.number == "2026-CR-0001"
    assert case.title == "Test Case"
    assert case.lead_examiner == "Investigator X"
    assert case.status == CaseStatus.OPEN
    assert case.is_deleted is False
    assert case.opened_at.tzinfo == UTC


def test_case_validation_rejects_empty_number() -> None:
    with pytest.raises(ValueError):
        Case(number="", title="Test", lead_examiner="Investigator X")


def test_case_validation_rejects_empty_title() -> None:
    with pytest.raises(ValueError):
        Case(number="2026-CR-0002", title="   ", lead_examiner="Investigator X")


def test_case_validation_rejects_empty_examiner() -> None:
    with pytest.raises(ValueError):
        Case(number="2026-CR-0003", title="Test", lead_examiner="")


def test_case_validation_rejects_naive_datetime() -> None:
    naive_dt = datetime.now()  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        Case(
            number="2026-CR-0004",
            title="Test",
            lead_examiner="Investigator X",
            opened_at=naive_dt,
        )


def test_case_validation_rejects_open_with_closed_at() -> None:
    with pytest.raises(ValueError, match="An OPEN case cannot have a closed_at timestamp"):
        Case(
            number="2026-CR-0005",
            title="Invalid Open",
            lead_examiner="Investigator X",
            status=CaseStatus.OPEN,
            closed_at=datetime.now(UTC),
        )


def test_case_tag_cleaning() -> None:
    case = Case(
        number="2026-CR-0006",
        title="Tag Test",
        lead_examiner="Investigator X",
        tags=["usb", "  usb ", "", "  laptop  "],
    )
    assert case.tags == ["usb", "laptop"]

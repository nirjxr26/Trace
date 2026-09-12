"""Readiness tests for Subpart-2 audit integration."""

from datetime import UTC, datetime

import pytest

from trace_core.cases.dto import CaseCreateDto, CaseFilterDto
from trace_core.cases.service import CaseService, InvalidCaseStateError
from trace_core.core.canonical import canonical_json
from trace_core.core.cli.output import parse_output_format

pytestmark = pytest.mark.unit


def test_canonical_json_key_order_and_compact() -> None:
    payload = {"z": 1, "a": {"d": 4, "b": 2}}
    assert canonical_json(payload) == b'{"a":{"b":2,"d":4},"z":1}'


def test_canonical_json_datetime_utc() -> None:
    naive = {"ts": datetime(2026, 9, 12, 10, 0, 0)}
    aware = {"ts": datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)}
    assert canonical_json(naive) == canonical_json(aware)
    assert canonical_json(aware) == b'{"ts":"2026-09-12T10:00:00Z"}'


def test_parse_output_format_defaults() -> None:
    assert parse_output_format([]) == "table"
    assert parse_output_format(["--output", "json"]) == "json"
    assert parse_output_format(["-o", "JSON"]) == "json"


def test_archive_restore_with_actor(service: CaseService) -> None:
    created = service.create_case(
        CaseCreateDto(title="Archive Test", lead_examiner="Examiner A"),
        actor="Examiner A",
    )
    assert service.delete_case(created.number, actor="Archivist") is True

    archived = service.get_case(created.number)
    assert archived.is_deleted is True
    assert archived.archived_at is not None
    assert archived.archived_by == "Archivist"

    active = service.list_cases(CaseFilterDto(include_deleted=False))
    assert not any(c.number == created.number for c in active)

    restored = service.restore_case(created.number)
    assert restored.is_deleted is False
    assert restored.archived_at is None
    assert restored.archived_by is None

    with pytest.raises(InvalidCaseStateError):
        service.restore_case(created.number)

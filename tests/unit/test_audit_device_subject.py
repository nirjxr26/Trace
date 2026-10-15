import json

import pytest

from trace_core.audit.domain import AuditAction, build_payload
from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.models import AuditEventModel
from trace_core.audit.repository import SqlAlchemyAuditRepository
from trace_core.core.clock import now_utc
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit

SERIAL_A = "SYNTH-1111111111111111"
SERIAL_B = "SYNTH-2222222222222222"
CASE = "2026-CR-0001"


def _append(session_manager: DatabaseSessionManager, action: AuditAction, serial=None, case_number=None):  # type: ignore[no-untyped-def]
    with session_manager.session() as session:
        dto = SqlAlchemyAuditRepository(session).append(
            action,
            "Ex",
            case_number,
            None,
            {},
            subject_type="case" if case_number else "device",
            subject_device_serial=serial,
        )
        session.commit()
        return dto


def _seed(session_manager: DatabaseSessionManager) -> None:
    _append(session_manager, AuditAction.DEVICE_INSPECTED, serial=SERIAL_A)
    _append(session_manager, AuditAction.DEVICE_GATE_CHECKED, serial=SERIAL_A)
    _append(session_manager, AuditAction.DEVICE_INSPECTED, serial=SERIAL_B)
    _append(session_manager, AuditAction.CASE_CREATED, case_number=CASE)


def _seqs(session_manager: DatabaseSessionManager, **filter_kwargs) -> list[int]:  # type: ignore[no-untyped-def]
    with session_manager.session() as session:
        rows = SqlAlchemyAuditRepository(session).list_events(AuditFilterDto(limit=50, **filter_kwargs))
    return [r.seq for r in rows]


def test_the_device_serial_is_a_payload_key_only_when_present() -> None:
    case = build_payload(AuditAction.CASE_CREATED, CASE, "Ex", {}, now_utc())
    device = build_payload(AuditAction.DEVICE_INSPECTED, None, "Ex", {}, now_utc())
    addressed = build_payload(AuditAction.DEVICE_INSPECTED, None, "Ex", {}, now_utc(), subject_device_serial=SERIAL_A)
    assert "subject_device_serial" not in case
    assert "subject_device_serial" not in device
    assert set(addressed) - set(device) == {"subject_device_serial"}
    assert addressed["subject_device_serial"] == SERIAL_A


def test_the_row_and_payload_store_the_subject_serial(session_manager: DatabaseSessionManager) -> None:
    dto = _append(session_manager, AuditAction.DEVICE_INSPECTED, serial=SERIAL_A)
    assert dto.subject_device_serial == SERIAL_A
    assert json.loads(dto.payload_json)["subject_device_serial"] == SERIAL_A
    with session_manager.session() as session:
        stored = session.get(AuditEventModel, dto.seq)
    assert stored is not None
    assert stored.subject_device_serial == SERIAL_A


def test_a_device_row_without_a_serial_stores_no_payload_key(session_manager: DatabaseSessionManager) -> None:
    dto = _append(session_manager, AuditAction.DEVICE_INSPECTED)
    assert dto.subject_device_serial is None
    assert "subject_device_serial" not in json.loads(dto.payload_json)


def test_the_device_filter_selects_exactly_one_identity(session_manager: DatabaseSessionManager) -> None:
    _seed(session_manager)
    assert _seqs(session_manager, device_serial=SERIAL_A) == [2, 1]
    assert _seqs(session_manager, device_serial=SERIAL_B) == [3]
    assert _seqs(session_manager, device_serial="SYNTH-1111") == []


def test_the_device_filter_is_exact_not_a_prefix(session_manager: DatabaseSessionManager) -> None:
    _append(session_manager, AuditAction.DEVICE_INSPECTED, serial="SN-1")
    _append(session_manager, AuditAction.DEVICE_INSPECTED, serial="SN-12")
    assert _seqs(session_manager, device_serial="SN-1") == [1]
    assert _seqs(session_manager, device_serial="SN-12") == [2]


def test_the_device_filter_composes_with_action_and_case(session_manager: DatabaseSessionManager) -> None:
    _seed(session_manager)
    assert _seqs(session_manager, device_serial=SERIAL_A, action=AuditAction.DEVICE_INSPECTED) == [1]
    assert _seqs(session_manager, device_serial=SERIAL_A, case_number=CASE) == []


def test_search_matches_a_device_serial_substring(session_manager: DatabaseSessionManager) -> None:
    _seed(session_manager)
    assert _seqs(session_manager, search="th-2222") == [3]
    assert _seqs(session_manager, search="synth-1111") == [2, 1]

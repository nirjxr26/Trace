import json

import pytest

from trace_core.audit.domain import AuditAction, build_payload
from trace_core.audit.dto import AuditEventDto
from trace_core.audit.events import Subject
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit

NO_CASE_LABEL = "(no case)"
CASE_NUMBER = "2026-CR-0001"
STAMP = ("2026-01-01T00:00:00Z",)


def _case_payload() -> dict:
    from trace_core.core.clock import now_utc

    return build_payload(AuditAction.CASE_CREATED, CASE_NUMBER, "Ex A", {}, now_utc())


def _device_payload() -> dict:
    from trace_core.core.clock import now_utc

    return build_payload(AuditAction.DEVICE_INSPECTED, None, "Ex A", {}, now_utc())


def test_payload_keeps_subject_case_number_key_for_a_non_case_subject() -> None:
    payload = _device_payload()
    assert "subject_case_number" in payload
    assert payload["subject_case_number"] is None


def test_case_payload_is_unchanged_by_d14() -> None:
    payload = _case_payload()
    assert payload["subject_case_number"] == CASE_NUMBER
    assert set(payload) == {
        "action",
        "actor",
        "subject_case_number",
        "ts",
        "spec",
        "canonicalization",
        "hash_algo",
        "details",
    }


def test_payload_key_serialises_as_json_null_rather_than_being_omitted() -> None:
    round_tripped = json.loads(json.dumps(_device_payload()))
    assert "subject_case_number" in round_tripped
    assert round_tripped["subject_case_number"] is None
    assert json.loads(json.dumps(_case_payload()))["subject_case_number"] == CASE_NUMBER


def test_subject_type_uses_the_lowercase_vocabulary_events_py_declares() -> None:
    subject = Subject(type="device", number=None, id=None)
    assert subject.type == "device"
    assert subject.number is None


def test_repository_rejects_an_unknown_subject_type(session_manager: DatabaseSessionManager) -> None:
    from trace_core.audit.repository import SqlAlchemyAuditRepository

    with session_manager.session() as session:
        with pytest.raises(ValueError, match="Unknown audit subject type"):
            SqlAlchemyAuditRepository(session).append(
                AuditAction.DEVICE_INSPECTED, "Ex A", None, None, {}, subject_type="DEVICE"
            )


def _append_device_event(session_manager: DatabaseSessionManager):
    from trace_core.audit.repository import SqlAlchemyAuditRepository

    with session_manager.session() as session:
        return SqlAlchemyAuditRepository(session).append(
            AuditAction.DEVICE_INSPECTED, "Ex A", None, None, {}, subject_type="device"
        )


def test_device_event_with_null_case_verifies(session_manager: DatabaseSessionManager) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="A", lead_examiner="Ex A"))
    _append_device_event(session_manager)

    result = AuditService(session_manager).verify()
    assert result.is_valid is True
    assert result.events_verified == 2


def test_device_event_reads_back_with_null_case_and_device_type(
    session_manager: DatabaseSessionManager,
) -> None:
    _append_device_event(session_manager)
    device = [e for e in AuditService(session_manager).list_events() if e.action is AuditAction.DEVICE_INSPECTED]
    assert len(device) == 1
    assert device[0].subject_case_number is None
    assert device[0].subject_type == "device"


def test_case_event_still_reads_back_with_its_number_and_case_type(
    session_manager: DatabaseSessionManager,
) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="A", lead_examiner="Ex A"))
    events = AuditService(session_manager).list_events()
    assert all(e.subject_type == "case" for e in events)
    assert all(e.subject_case_number is not None for e in events)


def test_export_emits_null_for_a_non_case_subject(session_manager: DatabaseSessionManager, tmp_path) -> None:
    _append_device_event(session_manager)
    out = AuditService(session_manager).export(str(tmp_path / "bundle.jsonl"))

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    data = [r for r in rows if "seq" in r]
    assert len(data) == 1
    assert "subject_case_number" in data[0]
    assert data[0]["subject_case_number"] is None


def test_export_then_decrypt_round_trips_a_non_case_subject(session_manager: DatabaseSessionManager, tmp_path) -> None:
    from trace_core.audit.helpers import do_decrypt, do_export_encrypted

    _append_device_event(session_manager)
    sealed = do_export_encrypted(AuditService(session_manager), str(tmp_path / "sealed.json"), "pw-test")
    plain = do_decrypt(str(sealed), str(tmp_path / "plain.json"), "pw-test")

    rows = [json.loads(line) for line in plain.read_text(encoding="utf-8").splitlines() if line]
    data = [r for r in rows if "seq" in r]
    assert len(data) == 1
    assert "subject_case_number" in data[0]
    assert data[0]["subject_case_number"] is None


def _dto(seq: int, action: AuditAction, number: str | None, subject_type: str) -> AuditEventDto:
    from datetime import UTC, datetime

    return AuditEventDto(
        seq=seq,
        ts=datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
        action=action,
        actor="Ex A",
        subject_type=subject_type,
        subject_case_number=number,
        payload_json=json.dumps(build_payload(action, number, "Ex A", {}, datetime(2026, 10, 3, 12, 0, tzinfo=UTC))),
        payload_hash="a" * 64,
        prev_chain="0" * 64,
        chain_hash="b" * 64,
    )


def _device_dto() -> AuditEventDto:
    return _dto(2, AuditAction.DEVICE_INSPECTED, None, "device")


def test_audit_table_never_renders_a_null_case_as_the_text_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from trace_core.audit.renderers import render_audit_table

    render_audit_table([_device_dto()])
    out = capsys.readouterr().out
    assert "None" not in out
    assert NO_CASE_LABEL in out


def test_audit_detail_never_renders_a_null_case_as_the_text_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from trace_core.audit.renderers import render_audit_detail

    render_audit_detail(_device_dto())
    out = capsys.readouterr().out
    assert "None" not in out
    assert NO_CASE_LABEL in out


def test_null_subject_does_not_inflate_case_cardinality(capsys: pytest.CaptureFixture[str]) -> None:
    from trace_core.audit.renderers import render_audit_table

    case_dto = _dto(1, AuditAction.CASE_CREATED, CASE_NUMBER, "case")
    render_audit_table([_device_dto(), case_dto])
    out = capsys.readouterr().out
    assert "2 cases" not in out
    assert "1 case" in out

"""Tribunal tests for Subpart-2 tamper-evident audit ledger."""

import hashlib
import json

import pytest
import sqlalchemy
import sqlalchemy.exc

from trace_core.audit.domain import GENESIS_CHAIN, chain_hash
from trace_core.audit.models import AuditEventModel
from trace_core.audit.repository import SqlAlchemyAuditRepository
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.canonical import canonical_json
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit


def test_clean_chain_verify(session_manager: DatabaseSessionManager) -> None:
    svc = CaseService(session_manager)
    svc.create_case(CaseCreateDto(title="A", lead_examiner="Ex A"))
    svc.create_case(CaseCreateDto(title="B", lead_examiner="Ex B"))
    audit = AuditService(session_manager)
    res = audit.verify()
    assert res.is_valid is True
    assert res.events_verified == 2
    assert res.first_mismatch_seq is None


def _disable_audit_triggers(conn) -> None:  # type: ignore[no-untyped-def]
    for ddl in ("DROP TRIGGER IF EXISTS audit_events_no_update", "DROP TRIGGER IF EXISTS audit_events_no_delete"):
        try:
            conn.execute(sqlalchemy.text(ddl))
        except Exception:
            pass


def _enable_audit_triggers(conn) -> None:  # type: ignore[no-untyped-def]
    for ddl in (
        "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END",
        "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END",
    ):
        try:
            conn.execute(sqlalchemy.text(ddl))
        except Exception:
            pass


def test_mutate_payload_json_detected(session_manager: DatabaseSessionManager) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="T1", lead_examiner="Ex"))
    with session_manager.engine.begin() as conn:
        _disable_audit_triggers(conn)
        conn.execute(
            sqlalchemy.text("UPDATE audit_events SET payload_json=REPLACE(payload_json, 'T1', 'HACKED') WHERE seq=1")
        )
        _enable_audit_triggers(conn)
    res = AuditService(session_manager).verify()
    assert res.is_valid is False
    assert res.mismatch_type == "payload_hash"
    assert res.first_mismatch_seq == 1


def test_mutate_payload_and_hash_still_chain_fails(session_manager: DatabaseSessionManager) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="T1", lead_examiner="Ex"))
    CaseService(session_manager).create_case(CaseCreateDto(title="T2", lead_examiner="Ex"))
    with session_manager.engine.begin() as conn:
        _disable_audit_triggers(conn)
        row = conn.execute(
            sqlalchemy.text("SELECT payload_json, prev_chain, seq FROM audit_events WHERE seq=1")
        ).fetchone()
        assert row is not None
        obj = json.loads(row[0])
        obj["details"]["title"] = "HACKED"
        new_json = canonical_json(obj).decode("utf-8")
        new_hash = hashlib.sha256(canonical_json(obj)).hexdigest()
        new_chain = chain_hash(row[1], new_hash, row[2])
        conn.execute(
            sqlalchemy.text("UPDATE audit_events SET payload_json=:j, payload_hash=:h, chain_hash=:c WHERE seq=1"),
            {"j": new_json, "h": new_hash, "c": new_chain},
        )
        _enable_audit_triggers(conn)
    res = AuditService(session_manager).verify()
    assert res.is_valid is False
    assert res.first_mismatch_seq == 1
    assert res.mismatch_type == "signature"


def test_mutate_chain_hash_detected(session_manager: DatabaseSessionManager) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="T1", lead_examiner="Ex"))
    with session_manager.engine.begin() as conn:
        _disable_audit_triggers(conn)
        conn.execute(sqlalchemy.text("UPDATE audit_events SET chain_hash=:h WHERE seq=1"), {"h": "f" * 64})
        _enable_audit_triggers(conn)
    res = AuditService(session_manager).verify()
    assert res.is_valid is False
    assert res.mismatch_type == "chain_hash"


def test_mutate_prev_chain_detected(session_manager: DatabaseSessionManager) -> None:
    for t in ("A", "B"):
        CaseService(session_manager).create_case(CaseCreateDto(title=t, lead_examiner="Ex"))
    with session_manager.engine.begin() as conn:
        _disable_audit_triggers(conn)
        conn.execute(sqlalchemy.text("UPDATE audit_events SET prev_chain=:h WHERE seq=2"), {"h": "0" * 64})
        _enable_audit_triggers(conn)
    res = AuditService(session_manager).verify()
    assert res.is_valid is False
    assert res.mismatch_type == "prev_chain"


def test_delete_middle_row_detected(session_manager: DatabaseSessionManager) -> None:
    for t in ("A", "B", "C"):
        CaseService(session_manager).create_case(CaseCreateDto(title=t, lead_examiner="Ex"))
    with session_manager.engine.begin() as conn:
        _disable_audit_triggers(conn)
        conn.execute(sqlalchemy.text("DELETE FROM audit_events WHERE seq=2"))
        _enable_audit_triggers(conn)
    res = AuditService(session_manager).verify()
    assert res.is_valid is False
    assert res.first_mismatch_seq == 3


def test_tail_deletion_is_not_internally_detected(session_manager: DatabaseSessionManager) -> None:
    for t in ("A", "B", "C"):
        CaseService(session_manager).create_case(CaseCreateDto(title=t, lead_examiner="Ex"))
    with session_manager.engine.begin() as conn:
        _disable_audit_triggers(conn)
        conn.execute(sqlalchemy.text("DELETE FROM audit_events WHERE seq=3"))
        _enable_audit_triggers(conn)
    res = AuditService(session_manager).verify()
    # truncated chain validates internally (V1 limitation, needs external anchor)
    assert res.is_valid is True
    assert res.last_seq == 2


def test_rollback_gap_is_warning_not_tamper(session_manager: DatabaseSessionManager) -> None:
    # manually craft gap 1,3
    CaseService(session_manager).create_case(CaseCreateDto(title="A", lead_examiner="Ex"))
    with session_manager.session() as s:
        # insert seq 3 manually with prev = chain of seq1
        m1 = s.scalars(sqlalchemy.select(AuditEventModel).where(AuditEventModel.seq == 1)).first()
        assert m1 is not None
        payload = {
            "action": "CASE_CREATED",
            "actor": "Ex",
            "subject_case_number": "GAP-1",
            "ts": "2026-01-01T00:00:00Z",
            "spec": "trace-audit-v1",
            "canonicalization": "trace-canonical-json-v1",
            "hash_algo": "SHA-256",
            "details": {},
        }
        p_bytes = canonical_json(payload)
        p_hash = hashlib.sha256(p_bytes).hexdigest()
        c_hash = chain_hash(m1.chain_hash, p_hash, 3)
        m3 = AuditEventModel(
            seq=3,
            ts=m1.ts,
            action="CASE_CREATED",
            actor="Ex",
            subject_case_number="GAP-1",
            subject_case_id=None,
            payload_json=p_bytes.decode("utf-8"),
            payload_hash=p_hash,
            prev_chain=m1.chain_hash,
            chain_hash=c_hash,
        )
        s.add(m3)
        # update head to 3
        from trace_core.audit.models import AuditChainStateModel

        head = s.get(AuditChainStateModel, 1)
        assert head is not None
        head.last_seq = 3
        head.last_chain_hash = c_hash
        s.commit()
    res = AuditService(session_manager).verify()
    assert res.is_valid is True
    assert 2 in res.sequence_gaps


def test_audit_failure_rolls_back_case(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = CaseService(session_manager)

    def failing_append(*_a: object, **_kw: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("audit write failed")

    with monkeypatch.context() as mp:
        mp.setattr(SqlAlchemyAuditRepository, "append", failing_append)
        failing_dto = CaseCreateDto(title="Fail", lead_examiner="Ex")
        with pytest.raises(RuntimeError, match="audit write failed"):
            svc.create_case(failing_dto)
        assert len(svc.list_cases()) == 0
        assert AuditService(session_manager).verify().events_verified == 0
    created = svc.create_case(CaseCreateDto(title="OK", lead_examiner="Ex"))
    assert created.title == "OK"


def _attempt_ledger_write(s, stmt: str) -> None:  # type: ignore[no-untyped-def]
    """Execute a tamper statement and commit. Single throwing call for narrow raises blocks."""
    s.execute(sqlalchemy.text(stmt))
    s.commit()


def test_triggers_reject_update_delete(session_manager: DatabaseSessionManager) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    with session_manager.session() as s:
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            _attempt_ledger_write(s, "UPDATE audit_events SET actor='hax' WHERE seq=1")
        s.rollback()
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            _attempt_ledger_write(s, "DELETE FROM audit_events WHERE seq=1")


def test_export_verifiable_offline(tmp_path, session_manager: DatabaseSessionManager) -> None:  # type: ignore[no-untyped-def]
    for t in ("A", "B"):
        CaseService(session_manager).create_case(CaseCreateDto(title=t, lead_examiner="Ex"))
    out = tmp_path / "bundle.jsonl"
    AuditService(session_manager).export(out)
    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # header + 2 events
    header = json.loads(lines[0])
    assert header["spec"] == "trace-audit-v1"
    # offline verify: recompute chain from exported file
    prev = GENESIS_CHAIN
    for line in lines[1:]:
        rec = json.loads(line)
        p_hash = hashlib.sha256(rec["payload_json"].encode("utf-8")).hexdigest()
        assert p_hash == rec["payload_hash"]
        exp_chain = chain_hash(rec["prev_chain"], p_hash, rec["seq"])
        assert exp_chain == rec["chain_hash"]
        assert rec["prev_chain"] == prev
        prev = rec["chain_hash"]


def test_canonical_key_order() -> None:
    a = {"z": 1, "a": {"d": 4, "b": 2}}
    b = {"a": {"b": 2, "d": 4}, "z": 1}
    assert canonical_json(a) == canonical_json(b)


def test_non_finite_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_json({"v": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"v": float("inf")})

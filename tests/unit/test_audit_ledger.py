"""Tribunal tests for Subpart-2 tamper-evident audit ledger."""

import hashlib
import json
from datetime import datetime
from uuid import UUID

import pytest
import sqlalchemy
import sqlalchemy.exc

from trace_core.audit.domain import GENESIS_CHAIN, AuditAction, chain_hash
from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.models import AuditEventModel
from trace_core.audit.repository import SqlAlchemyAuditRepository, _model_to_dto
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.canonical import canonical_json
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit


def test_chain_hash_refuses_inputs_that_are_not_sha256_hex() -> None:
    """The concatenation is only unambiguous when both hashes are exactly 64 chars."""
    from trace_core.core.domain import InvariantViolationError

    digest = "a" * 64
    with pytest.raises(InvariantViolationError):
        chain_hash("a" * 63, digest, 1)
    with pytest.raises(InvariantViolationError):
        chain_hash(digest, "b" * 65, 1)
    assert chain_hash(digest, digest, 1)


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


def _tamper_seq_one(session_manager: DatabaseSessionManager) -> None:
    """Break the chain hash of seq 1 behind the append-only triggers.

    One invocation, so a failure points at the tamper and not at a neighbour in the same
    `pytest.raises` block that could also throw.
    """
    with session_manager.engine.begin() as conn:
        _disable_audit_triggers(conn)
        conn.execute(sqlalchemy.text("UPDATE audit_events SET chain_hash=:h WHERE seq=1"), {"h": "f" * 64})
        _enable_audit_triggers(conn)


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


def test_the_shared_verify_core_refuses_a_tampered_chain(
    session_manager: DatabaseSessionManager,
) -> None:
    """`do_verify` owns the Tamper policy, so no surface can report a broken chain as valid."""
    from trace_core.audit.helpers import do_verify
    from trace_core.core.errors import AuditTamperError

    CaseService(session_manager).create_case(CaseCreateDto(title="A", lead_examiner="Ex"))
    CaseService(session_manager).create_case(CaseCreateDto(title="B", lead_examiner="Ex"))
    assert do_verify(AuditService(session_manager), "json", None).is_valid is True
    _tamper_seq_one(session_manager)
    with pytest.raises(AuditTamperError, match="Tamper detected at seq 1"):
        do_verify(AuditService(session_manager), "json", None)


def test_the_repl_verify_surface_refuses_a_tampered_chain(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trace_core.audit.shell_handler import AuditShellCommandHandler
    from trace_core.core.cli.registry import ShellContext

    CaseService(session_manager).create_case(CaseCreateDto(title="A", lead_examiner="Ex"))
    CaseService(session_manager).create_case(CaseCreateDto(title="B", lead_examiner="Ex"))
    _tamper_seq_one(session_manager)

    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    rendered: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(
        "trace_core.core.cli.error_handler.render_error_card",
        lambda title, message, remediation=None: rendered.append((title, message, remediation)),
    )
    assert AuditShellCommandHandler().execute("verify", [], ShellContext()) is True
    assert [title for title, _, _ in rendered] == ["Audit Verify"], rendered
    assert "Tamper detected" in rendered[0][1]


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


def test_append_retries_transient_head_collision(session_manager, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A transient seq/head conflict retries on a savepoint instead of failing the case write."""
    from sqlalchemy.exc import IntegrityError

    from trace_core.audit.domain import AuditAction

    calls = {"n": 0}
    orig = SqlAlchemyAuditRepository._append_locked

    def flaky(self, *a, **k):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] < 3:
            raise IntegrityError("INSERT", {}, Exception("collision"))
        return orig(self, *a, **k)

    monkeypatch.setattr(SqlAlchemyAuditRepository, "_append_locked", flaky)
    with session_manager.session() as s:
        dto = SqlAlchemyAuditRepository(s).append(
            AuditAction.CASE_CREATED, "Ex", "2026-CR-0001", None, {}, subject_type="case"
        )
    assert dto.seq == 1
    assert calls["n"] == 3


def test_verify_gaps_capped() -> None:
    """An absurd seq jump is recorded bounded, valid, and never OOMs the detector."""
    from trace_core.audit.domain import AuditAction, build_payload, payload_hash
    from trace_core.audit.verifier import _MAX_GAPS, verify_rows
    from trace_core.core.canonical import canonical_json_str
    from trace_core.core.clock import now_utc

    def _row(seq, prev):  # type: ignore[no-untyped-def]
        payload = build_payload(AuditAction.CASE_CREATED, "2026-CR-0001", "Ex", {}, now_utc())
        body = canonical_json_str(payload)
        hashed = payload_hash(payload)
        chained = chain_hash(prev, hashed, seq)
        return AuditEventModel(
            seq=seq,
            ts=now_utc(),
            action="CASE_CREATED",
            actor="Ex",
            subject_case_number="2026-CR-0001",
            payload_json=body,
            payload_hash=hashed,
            prev_chain=prev,
            chain_hash=chained,
        )

    first = _row(1, GENESIS_CHAIN)
    jumped = _row(10**12, first.chain_hash)
    res = verify_rows([first, jumped])
    assert res.is_valid is True
    assert len(res.sequence_gaps) <= _MAX_GAPS


def test_export_header_carries_tip(tmp_path, session_manager: DatabaseSessionManager) -> None:
    """Bundle header names the tip so tail truncation is checkable without an anchor."""
    CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    out = tmp_path / "tip.jsonl"
    AuditService(session_manager).export(out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    header, last = json.loads(lines[0]), json.loads(lines[-1])
    assert header["last_seq"] == 1
    assert header["last_chain"] == last["chain_hash"]


_EXPORT_RECORD_KEYS = [
    "seq",
    "ts",
    "action",
    "actor",
    "subject_case_number",
    "subject_case_id",
    "payload_json",
    "payload_hash",
    "prev_chain",
    "chain_hash",
    "key_id",
    "signature",
]


def _exported_records(out) -> list[dict]:  # type: ignore[no-untyped-def]
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines[1:]]


def test_export_record_key_order_is_pinned(tmp_path, session_manager: DatabaseSessionManager) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="Order", lead_examiner="Ex"))
    out = tmp_path / "order.jsonl"
    AuditService(session_manager).export(out)
    assert list(_exported_records(out)[0].keys()) == _EXPORT_RECORD_KEYS


def test_export_omits_subject_type_by_design(tmp_path, session_manager: DatabaseSessionManager) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="NoSubj", lead_examiner="Ex"))
    with session_manager.session() as s:
        SqlAlchemyAuditRepository(s).append(
            AuditAction.DEVICE_INSPECTED, "Ex", None, None, {"device": "USB-1"}, subject_type="device"
        )
    out = tmp_path / "nosubj.jsonl"
    AuditService(session_manager).export(out)
    records = _exported_records(out)
    assert all("subject_type" not in r for r in records)
    with session_manager.session() as s:
        dto = SqlAlchemyAuditRepository(s).list_events(AuditFilterDto(limit=10))
    assert all(e.subject_type in {"case", "device"} for e in dto)


def test_export_record_line_is_byte_for_byte_stable(tmp_path, session_manager: DatabaseSessionManager) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="Bytes", lead_examiner="Ex"))
    out = tmp_path / "bytes.jsonl"
    AuditService(session_manager).export(out)
    raw = out.read_bytes()
    line = raw.split(b"\n")[1]
    assert line.startswith(b'{"seq": 1, "ts": "')
    assert b'", "action": "CASE_CREATED", "actor": "Ex", "subject_case_number": "2026-CR-0001"' in line
    assert b'", "payload_json": "{\\"action\\":\\"CASE_CREATED\\"' in line
    assert line.endswith(b"}")
    assert b'"key_id": "hmac-v1", "signature": "' in line
    assert raw.endswith(b"\n")


def test_export_handles_all_nullable_fields_null(tmp_path, session_manager: DatabaseSessionManager) -> None:
    with session_manager.session() as s:
        SqlAlchemyAuditRepository(s).append(
            AuditAction.DEVICE_INSPECTED, "Ex", None, None, {"device": "USB-2"}, subject_type="device"
        )
    out = tmp_path / "nulls.jsonl"
    AuditService(session_manager).export(out)
    record = _exported_records(out)[0]
    assert record["subject_case_number"] is None
    assert record["subject_case_id"] is None
    assert list(record.keys()) == _EXPORT_RECORD_KEYS


def test_dto_and_export_disagree_only_on_the_three_documented_fields(
    tmp_path, session_manager: DatabaseSessionManager
) -> None:
    CaseService(session_manager).create_case(CaseCreateDto(title="Diverge", lead_examiner="Ex"))
    out = tmp_path / "diverge.jsonl"
    AuditService(session_manager).export(out)
    exported = _exported_records(out)[0]
    with session_manager.session() as s:
        model = s.get(AuditEventModel, 1)
        assert model is not None
        dto = _model_to_dto(model)
    assert isinstance(dto.ts, datetime)
    assert dto.ts.tzinfo is not None
    assert isinstance(exported["ts"], str)
    assert exported["ts"].endswith("Z")
    assert dto.action is AuditAction.CASE_CREATED
    assert exported["action"] == "CASE_CREATED"
    assert isinstance(dto.subject_case_id, UUID)
    assert exported["subject_case_id"] == str(dto.subject_case_id)
    assert set(dto.model_dump()) - set(exported) == {"subject_type"}

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import text

from trace_core.audit.anchor import verify_against_anchor
from trace_core.audit.models import AuditChainStateModel, AuditEventModel
from trace_core.audit.service import AuditService
from trace_core.core.database.migrations import (
    AUDIT_DEVICE_SERIAL_COLUMN,
    AUDIT_DEVICE_SERIAL_INDEX,
    apply_migrations,
)
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import AnchorVerificationError, AuditTamperError

pytestmark = pytest.mark.unit

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "audit_legacy_ledger_v1.json"
IMMUTABLE_FIELDS = ("payload_json", "payload_hash", "prev_chain", "chain_hash", "signature")
REINSTATE_NO_UPDATE_TRIGGER = (
    "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
)


def _frozen() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _load(session, frozen: dict) -> None:
    for r in frozen["rows"]:
        session.add(
            AuditEventModel(
                seq=r["seq"],
                ts=datetime.fromisoformat(r["ts"]),
                action=r["action"],
                actor=r["actor"],
                subject_type=r["subject_type"],
                subject_case_number=r["subject_case_number"],
                subject_case_id=uuid.UUID(r["subject_case_id"]) if r["subject_case_id"] else None,
                payload_json=r["payload_json"],
                payload_hash=r["payload_hash"],
                prev_chain=r["prev_chain"],
                chain_hash=r["chain_hash"],
                key_id=r["key_id"],
                signature=r["signature"],
            )
        )
    state = session.get(AuditChainStateModel, 1)
    if state is None:
        state = AuditChainStateModel(id=1)
        session.add(state)
    state.last_seq = frozen["head"]["last_seq"]
    state.last_chain_hash = frozen["head"]["last_chain"]
    session.commit()


def _write_anchor(tmp_path: Path, frozen: dict, **overrides) -> Path:
    path = tmp_path / "anchor-2026-CR-0001-8.json"
    path.write_text(json.dumps({**frozen["anchor"], **overrides}), encoding="utf-8")
    return path


def _snapshot(manager: DatabaseSessionManager) -> dict:
    with manager.session() as session:
        rows = session.scalars(sqlalchemy.select(AuditEventModel)).all()
        return {row.seq: tuple(getattr(row, field) for field in IMMUTABLE_FIELDS) for row in rows}


def test_a_ledger_recorded_before_device_subjects_still_verifies(
    session_manager: DatabaseSessionManager, tmp_path: Path
) -> None:
    frozen = _frozen()
    with session_manager.session() as session:
        _load(session, frozen)
    svc = AuditService(session_manager)
    res = svc.verify()
    assert res.is_valid is True
    assert res.events_verified == len(frozen["rows"])
    assert res.first_mismatch_seq is None
    verify_against_anchor(svc, res, str(_write_anchor(tmp_path, frozen)))


def test_the_frozen_rows_predate_the_device_subject_serial(session_manager: DatabaseSessionManager) -> None:
    frozen = _frozen()
    with session_manager.session() as session:
        _load(session, frozen)
    with session_manager.session() as session:
        serials = session.scalars(sqlalchemy.select(AuditEventModel.subject_device_serial)).all()
    assert list(serials) == [None] * len(frozen["rows"])
    device_payloads = [r["payload_json"] for r in frozen["rows"] if r["subject_type"] == "device"]
    assert device_payloads
    assert all("subject_device_serial" not in json.loads(p) for p in device_payloads)


def test_the_frozen_payloads_are_what_the_verifier_checks(session_manager: DatabaseSessionManager) -> None:
    frozen = _frozen()
    seq = next(r["seq"] for r in frozen["rows"] if r["subject_type"] == "device")
    with session_manager.session() as session:
        _load(session, frozen)
    with session_manager.engine.begin() as conn:
        conn.execute(text("DROP TRIGGER IF EXISTS audit_events_no_update"))
        changed = conn.execute(
            text(
                "UPDATE audit_events SET payload_json = REPLACE(payload_json, 'DEVICE_INSPECTED', 'DEVICE_REMOVED') "
                "WHERE seq = :seq"
            ),
            {"seq": seq},
        ).rowcount
        conn.execute(text(REINSTATE_NO_UPDATE_TRIGGER))
    assert changed == 1
    res = AuditService(session_manager).verify()
    assert res.is_valid is False
    assert res.mismatch_type == "payload_hash"
    assert res.first_mismatch_seq == seq


def test_the_frozen_anchor_is_actually_compared(session_manager: DatabaseSessionManager, tmp_path: Path) -> None:
    frozen = _frozen()
    with session_manager.session() as session:
        _load(session, frozen)
    svc = AuditService(session_manager)
    res = svc.verify()
    with pytest.raises(AuditTamperError):
        verify_against_anchor(svc, res, str(_write_anchor(tmp_path, frozen, last_chain="f" * 64)))
    with pytest.raises(AnchorVerificationError):
        verify_against_anchor(svc, res, str(_write_anchor(tmp_path, frozen, signature="0" * 128)))


def test_migrating_a_frozen_ledger_to_022_leaves_every_row_byte_identical(
    tmp_path: Path,
) -> None:
    frozen = _frozen()
    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    apply_migrations(manager.engine)
    with manager.session() as session:
        _load(session, frozen)
    before = _snapshot(manager)
    with manager.engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {AUDIT_DEVICE_SERIAL_INDEX}"))
        conn.execute(text(f"ALTER TABLE audit_events DROP COLUMN {AUDIT_DEVICE_SERIAL_COLUMN}"))
        conn.execute(text("DELETE FROM schema_migrations WHERE version = 22"))
    apply_migrations(manager.engine)
    assert _snapshot(manager) == before
    svc = AuditService(manager)
    res = svc.verify()
    assert res.is_valid is True
    assert res.events_verified == len(frozen["rows"])
    verify_against_anchor(svc, res, str(_write_anchor(tmp_path, frozen)))

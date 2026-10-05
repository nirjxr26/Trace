"""Migration 017 exercised against the pre-017 audit_events shape."""

import json

import pytest
from sqlalchemy import create_engine, inspect, text

from trace_core.audit.domain import GENESIS_CHAIN, chain_hash, payload_hash
from trace_core.core.database.migrations import (
    _column_names,
    _index_exists,
    _run_migration_017,
    _verify_008_audit_protection,
)

pytestmark = pytest.mark.unit

PRE_017_DDL = """
CREATE TABLE audit_events (
    seq INTEGER NOT NULL,
    ts DATETIME NOT NULL,
    action VARCHAR(50) NOT NULL,
    actor VARCHAR(255) NOT NULL,
    subject_case_number TEXT NOT NULL,
    subject_case_id BLOB,
    payload_json TEXT NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    prev_chain VARCHAR(64) NOT NULL,
    chain_hash VARCHAR(64) NOT NULL,
    key_id VARCHAR(64),
    signature VARCHAR(128),
    PRIMARY KEY (seq)
)
"""

PRE_017_INDEXES = (
    "CREATE INDEX ix_audit_events_ts ON audit_events (ts)",
    "CREATE INDEX ix_audit_events_action ON audit_events (action)",
    "CREATE INDEX ix_audit_events_actor ON audit_events (actor)",
    "CREATE INDEX ix_audit_events_subject_case_number ON audit_events (subject_case_number)",
    "CREATE INDEX idx_audit_case_seq ON audit_events (subject_case_number, seq DESC)",
)

PRE_017_TRIGGERS = (
    "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END",
    "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END",
)


def _payload(case_number: str) -> dict:
    return {
        "action": "CASE_CREATED",
        "actor": "Ex A",
        "subject_case_number": case_number,
        "ts": "2026-01-01T00:00:00Z",
        "spec": "trace-audit-v1",
        "canonicalization": "trace-canonical-json-v1",
        "hash_algo": "SHA-256",
        "details": {},
    }


def _seed(engine) -> dict:
    payload = _payload("2026-CR-0001")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    p_hash = payload_hash(payload)
    c_hash = chain_hash(GENESIS_CHAIN, p_hash, 1)
    with engine.begin() as conn:
        conn.execute(text(PRE_017_DDL))
        for ddl in PRE_017_INDEXES + PRE_017_TRIGGERS:
            conn.execute(text(ddl))
        conn.execute(
            text(
                "INSERT INTO audit_events (seq, ts, action, actor, subject_case_number, "
                "subject_case_id, payload_json, payload_hash, prev_chain, chain_hash) "
                "VALUES (1, '2026-01-01 00:00:00', 'CASE_CREATED', 'Ex A', '2026-CR-0001', "
                "NULL, :pj, :ph, :pc, :ch)"
            ),
            {"pj": raw.decode(), "ph": p_hash, "pc": GENESIS_CHAIN, "ch": c_hash},
        )
    return {"payload_json": raw.decode(), "payload_hash": p_hash, "chain_hash": c_hash}


@pytest.fixture
def pre_017_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pre017.db'}")
    _seed(engine)
    return engine


HASH_FIELDS = "payload_json, payload_hash, prev_chain, chain_hash"


def _stored(engine, with_type: bool = True) -> dict:
    columns = f"{HASH_FIELDS}, subject_type" if with_type else HASH_FIELDS
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT {columns} FROM audit_events WHERE seq = 1")).fetchone()
    return dict(row._mapping)


def test_migration_017_backfills_existing_rows_as_case(pre_017_engine) -> None:
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
    assert _stored(pre_017_engine)["subject_type"] == "case"


def test_migration_017_leaves_payload_and_hashes_byte_identical(pre_017_engine) -> None:
    before = _stored(pre_017_engine, with_type=False)
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
    after = _stored(pre_017_engine)
    for field in ("payload_json", "payload_hash", "prev_chain", "chain_hash"):
        assert after[field] == before[field], field


def test_migration_017_relaxes_subject_case_number_not_null(pre_017_engine) -> None:
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
        columns = {c["name"]: c for c in inspect(conn).get_columns("audit_events")}
    assert columns["subject_case_number"]["nullable"] is True
    assert columns["subject_type"]["nullable"] is False


def test_migration_017_allows_a_null_case_row(pre_017_engine) -> None:
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
        conn.execute(
            text(
                "INSERT INTO audit_events (seq, ts, action, actor, subject_type, "
                "subject_case_number, payload_json, payload_hash, prev_chain, chain_hash) "
                "VALUES (2, '2026-01-01 00:00:00', 'DEVICE_INSPECTED', 'Ex A', 'device', "
                "NULL, '{}', :ph, '0', '1')"
            ),
            {"ph": "a" * 64},
        )
    assert _stored(pre_017_engine)["subject_type"] == "case"


def test_migration_017_restores_the_append_only_trigger(pre_017_engine) -> None:
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
        assert _verify_008_audit_protection(conn) is True
    from sqlalchemy.exc import DBAPIError

    def _tamper_update() -> None:
        with pre_017_engine.begin() as conn:
            conn.execute(text("UPDATE audit_events SET actor = 'tampered' WHERE seq = 1"))

    def _tamper_delete() -> None:
        with pre_017_engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_events WHERE seq = 1"))

    with pytest.raises(DBAPIError):
        _tamper_update()
    with pytest.raises(DBAPIError):
        _tamper_delete()


def test_migration_017_preserves_every_pre_existing_index(pre_017_engine) -> None:
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
    expected = {
        "ix_audit_events_ts",
        "ix_audit_events_action",
        "ix_audit_events_actor",
        "ix_audit_events_subject_case_number",
        "idx_audit_case_seq",
        "ix_audit_events_subject_type",
    }
    with pre_017_engine.connect() as conn:
        present = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='audit_events'")
            ).fetchall()
        }
    assert expected <= present


def test_migration_017_preserves_row_count_and_column_count(pre_017_engine) -> None:
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar() == 1
        assert len(_column_names(conn, "audit_events")) == 13


def test_migration_017_is_idempotent(pre_017_engine) -> None:
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
    before = _stored(pre_017_engine)
    with pre_017_engine.begin() as conn:
        _run_migration_017(conn)
    assert _stored(pre_017_engine) == before
    with pre_017_engine.connect() as conn:
        assert _index_exists(conn, "audit_events", "ix_audit_events_subject_type") is True

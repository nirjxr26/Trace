"""Integration tests running against real PostgreSQL database when available."""

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from trace_core.audit.domain import GENESIS_CHAIN, chain_hash, payload_hash
from trace_core.cases.domain import CaseStatus
from trace_core.cases.dto import CaseCreateDto, CaseFilterDto, CaseUpdateDto
from trace_core.cases.service import CaseService
from trace_core.core.canonical import canonical_json_str
from trace_core.core.database.migrations import (
    _verify_008_audit_protection,
    get_applied_migrations,
    get_table_names,
)
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.integration


def get_postgres_url() -> str | None:
    """PostgreSQL test URL, from the dedicated opt-in variable only.

    H-76: this fell back to TRACE_DATABASE_URL, so a developer with a production URL in
    their shell ran this suite against production — and these tests create, close, archive
    and permanently purge cases. There is no fallback; the suite refuses to start unless
    TRACE_TEST_POSTGRES_URL is set explicitly.
    """
    url = os.environ.get("TRACE_TEST_POSTGRES_URL")
    if url and "postgres" in url.lower():
        return url
    return None


@pytest.fixture
def pg_session_manager() -> DatabaseSessionManager:
    """Provide a DatabaseSessionManager connected to PostgreSQL, or skip if unavailable."""
    pg_url = get_postgres_url()
    if not pg_url:
        pytest.skip("PostgreSQL environment not configured (set TRACE_TEST_POSTGRES_URL)")

    mgr = DatabaseSessionManager(pg_url)
    is_healthy, _ = mgr.check_connection()
    if not is_healthy:
        pytest.skip("Cannot reach configured PostgreSQL service")

    # Assert dialect is genuinely PostgreSQL, failing loudly if an unexpected fallback occurred
    assert mgr.engine.dialect.name == "postgresql", f"Expected postgresql dialect, got {mgr.engine.dialect.name}"

    with mgr.engine.connect() as conn:
        db_version = conn.execute(text("SELECT version();")).scalar()
        assert db_version is not None
        assert "postgresql" in str(db_version).lower()

    mgr.init_schema()
    return mgr


def test_postgres_integration_lifecycle(pg_session_manager: DatabaseSessionManager) -> None:
    """Verify full case lifecycle, migrations, and concurrency on real PostgreSQL."""
    # 1. Verify PostgreSQL dialect and schema tables
    assert pg_session_manager.engine.dialect.name == "postgresql"
    tables = get_table_names(pg_session_manager.engine)
    assert "cases" in tables
    assert "case_sequences" in tables
    assert "schema_migrations" in tables

    applied = get_applied_migrations(pg_session_manager.engine)
    assert any(m["name"] == "001_initial_case_schema" for m in applied)

    # 2. Case CRUD and sequence generation
    service = CaseService(pg_session_manager)
    uid = uuid.uuid4().hex[:6]
    dto = CaseCreateDto(
        title=f"PostgreSQL Integration Case {uid}",
        lead_examiner="Agent Mulder",
        notes="PostgreSQL database integration verification",
        tags=["postgres", "integration", "ci"],
    )
    created = service.create_case(dto)
    assert created.id is not None
    assert created.status == CaseStatus.OPEN
    assert created.version == 1

    # 3. Optimistic concurrency update
    updated = service.update_case(created.number, CaseUpdateDto(title=f"Updated Case {uid}"))
    assert updated.version == 2
    assert updated.title == f"Updated Case {uid}"

    # 4. Search and pagination
    results = service.list_cases(CaseFilterDto(search=uid, limit=10))
    assert len(results) >= 1
    assert any(c.number == created.number for c in results)

    # 5. Close case
    closed = service.close_case(created.number, reason="PostgreSQL test complete", closed_by="CI Runner")
    assert closed.status == CaseStatus.CLOSED

    # 6. Soft delete then purge
    assert service.delete_case(created.number, purge=False) is True
    assert service.delete_case(created.number, purge=True) is True


def _attempt_tamper_write(session, stmt: str) -> None:  # type: ignore[no-untyped-def]
    """Execute a tamper statement and flush. Single throwing call for narrow raises blocks."""
    session.execute(text(stmt))
    session.flush()


def test_postgres_audit_append_only(pg_session_manager: DatabaseSessionManager) -> None:
    """Verify the 008 trigger rejects ledger UPDATE/DELETE on PostgreSQL (parity row 1)."""
    from trace_core.core.database.migrations import get_applied_migrations

    assert any(
        m["name"] == "008_audit_append_only_protection" for m in get_applied_migrations(pg_session_manager.engine)
    )

    service = CaseService(pg_session_manager)
    uid = uuid.uuid4().hex[:6]
    created = service.create_case(CaseCreateDto(title=f"AppendOnly {uid}", lead_examiner="Agent Mulder"))
    try:
        with pg_session_manager.session() as session:
            for stmt in ("UPDATE audit_events SET actor = 'mallory'", "DELETE FROM audit_events"):
                with pytest.raises(DBAPIError):
                    _attempt_tamper_write(session, stmt)
                session.rollback()
    finally:
        service.delete_case(created.number, purge=False)
        service.delete_case(created.number, purge=True)


def test_postgres_concurrent_sequence_allocation(pg_session_manager: DatabaseSessionManager) -> None:
    """Verify concurrent case creation from cold sequence on PostgreSQL generates unique numbers."""
    service = CaseService(pg_session_manager)
    created_cases = []

    def create_case(idx: int) -> str:
        dto = CaseCreateDto(
            title=f"Concurrent Test {idx}",
            lead_examiner=f"Investigator {idx}",
        )
        c = service.create_case(dto)
        return c.number

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(create_case, i) for i in range(5)]
        created_cases = [f.result() for f in futures]

    assert len(created_cases) == 5
    assert len(set(created_cases)) == 5  # Every case number is unique

    # Clean up created test cases
    for num in created_cases:
        service.delete_case(num, purge=False)
        service.delete_case(num, purge=True)


def _pg_audit_columns(conn) -> dict:
    return {c["name"]: c for c in inspect(conn).get_columns("audit_events")}


def _pg_unlabelled(conn) -> int:
    return int(conn.execute(text("SELECT count(*) FROM audit_events WHERE subject_type IS NULL")).scalar() or 0)


def test_postgres_migration_017_backfills_and_relaxes(pg_session_manager: DatabaseSessionManager) -> None:
    with pg_session_manager.engine.connect() as conn:
        columns = _pg_audit_columns(conn)
        assert "subject_type" in columns, "migration 017 did not add subject_type"
        assert columns["subject_case_number"]["nullable"] is True
        assert columns["subject_type"]["nullable"] is False
        assert _pg_unlabelled(conn) == 0


def test_postgres_migration_017_backfill_preserves_hashes(
    pg_session_manager: DatabaseSessionManager,
) -> None:
    with pg_session_manager.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT seq, payload_json, payload_hash, prev_chain, chain_hash FROM audit_events ORDER BY seq")
        ).fetchall()
        for row in rows:
            payload = json.loads(row.payload_json)
            assert "subject_case_number" in payload
            assert payload_hash(payload) == row.payload_hash
            assert chain_hash(row.prev_chain, row.payload_hash, row.seq) == row.chain_hash


def test_postgres_migration_017_preserves_append_only_trigger(
    pg_session_manager: DatabaseSessionManager,
) -> None:
    with pg_session_manager.engine.connect() as conn:
        assert _verify_008_audit_protection(conn) is True

    def _tamper() -> None:
        with pg_session_manager.engine.begin() as conn:
            conn.execute(text("UPDATE audit_events SET actor = 'tampered' WHERE seq = 1"))

    with pytest.raises(DBAPIError):
        _tamper()


def test_postgres_migration_017_accepts_a_null_case_row(
    pg_session_manager: DatabaseSessionManager,
) -> None:
    with pg_session_manager.engine.begin() as conn:
        probe_seq = conn.execute(text("SELECT COALESCE(MAX(seq), 0) FROM audit_events")).scalar_one() + 1
        payload: dict[str, object] = {
            "action": "DEVICE_INSPECTED",
            "actor": "Ex A",
            "subject_case_number": None,
            "ts": "2026-01-01T00:00:00Z",
            "spec": "trace-audit-v1",
            "canonicalization": "trace-canonical-json-v1",
            "hash_algo": "SHA-256",
            "details": {},
        }
        p_hash = payload_hash(payload)
        c_hash = chain_hash(GENESIS_CHAIN, p_hash, probe_seq)
        conn.execute(
            text(
                "INSERT INTO audit_events (seq, ts, action, actor, subject_type, "
                "subject_case_number, payload_json, payload_hash, prev_chain, chain_hash) "
                "VALUES (:seq, now(), 'DEVICE_INSPECTED', 'Ex A', 'device', NULL, "
                ":pj, :ph, :pc, :ch)"
            ),
            {
                "seq": probe_seq,
                "pj": canonical_json_str(payload),
                "ph": p_hash,
                "pc": GENESIS_CHAIN,
                "ch": c_hash,
            },
        )
    with pg_session_manager.engine.begin() as conn:
        row = conn.execute(
            text("SELECT subject_case_number, subject_type FROM audit_events WHERE seq = :seq"),
            {"seq": probe_seq},
        ).fetchone()
        assert row is not None
        assert row.subject_case_number is None
        assert row.subject_type == "device"

"""Integration tests running against real PostgreSQL database when available."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from trace_core.cases.domain import CaseStatus
from trace_core.cases.dto import CaseCreateDto, CaseFilterDto, CaseUpdateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.migrations import get_applied_migrations, get_table_names
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.integration


def get_postgres_url() -> str | None:
    """Retrieve PostgreSQL test connection URL from environment if configured."""
    url = os.environ.get("TRACE_TEST_POSTGRES_URL") or os.environ.get("TRACE_DATABASE_URL")
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
                with pytest.raises(Exception):
                    session.execute(text(stmt))
                    session.flush()
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

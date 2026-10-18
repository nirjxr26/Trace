"""Tests for database lifecycle, connection health checks, migrations, and CLI db commands."""

from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy
import sqlalchemy.exc
from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.core.database.migrations import (
    apply_migrations,
    get_applied_migrations,
    get_pending_migrations,
    get_table_names,
)
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.service import BaseService, UnitOfWork
from trace_core.core.settings import Settings


def test_database_check_connection_success(session_manager: DatabaseSessionManager) -> None:
    """Verify check_connection returns True when database is reachable."""
    is_healthy, message = session_manager.check_connection()
    assert is_healthy is True
    assert "successful" in message.lower()


def test_database_check_connection_failure() -> None:
    """Verify check_connection returns False and error message on bad connection."""
    bad_mgr = DatabaseSessionManager("sqlite:////nonexistent/path/cannot_create.db")
    is_healthy, message = bad_mgr.check_connection()
    assert is_healthy is False
    assert "failed" in message.lower()


def test_settings_storage_error_logging() -> None:
    """Verify Settings.model_post_init logs a warning on OSError rather than crashing."""
    with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
        with patch("trace_core.core.settings.logger.warning") as mock_warning:
            Settings()
            mock_warning.assert_called_once()


def test_a_stray_dot_env_in_another_directory_is_not_loaded(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TRACE_DEVICE_ADAPTER=linux\n", encoding="utf-8")
    assert Settings().device_adapter != "linux", "the loader fell back to a cwd-relative .env"


def test_an_unknown_trace_setting_is_named_in_a_warning(monkeypatch) -> None:
    monkeypatch.setenv("TRACE_ZX_TYPO", "1")
    with patch("trace_core.core.settings.logger.warning") as mock_warning:
        Settings()
    named = [str(call) for call in mock_warning.call_args_list]
    assert any("TRACE_ZX_TYPO" in call for call in named), named


def test_case_column_definitions_match_model() -> None:
    """Backfill DDL must stay in agreement with the live CaseModel columns."""
    from trace_core.cases.models import CaseModel
    from trace_core.core.database.migrations import _CASE_COLUMN_DEFINITIONS

    model_columns = {c.name for c in CaseModel.__table__.columns}
    for col_name, _ddl in _CASE_COLUMN_DEFINITIONS:
        assert col_name in model_columns, f"backfill column {col_name!r} missing from CaseModel"


def test_migrations_tracking_and_idempotency() -> None:
    """Verify migration tracking, pending status, and idempotent re-application."""
    mgr = DatabaseSessionManager("sqlite:///:memory:")
    # Before applying migrations
    pending_before = get_pending_migrations(mgr.engine)
    assert len(pending_before) >= 1
    assert pending_before[0][0] == 1

    # Apply migrations
    applied_first = apply_migrations(mgr.engine)
    assert len(applied_first) >= 1
    assert "001_initial_case_schema" in applied_first

    # Check applied list
    applied_records = get_applied_migrations(mgr.engine)
    assert len(applied_records) >= 1
    assert applied_records[0]["name"] == "001_initial_case_schema"

    # Pending list should now be empty
    pending_after = get_pending_migrations(mgr.engine)
    assert len(pending_after) == 0

    # Tables should exist
    tables = get_table_names(mgr.engine)
    assert "cases" in tables
    assert "case_sequences" in tables
    assert "schema_migrations" in tables

    # Applying again should be a no-op
    applied_second = apply_migrations(mgr.engine)
    assert len(applied_second) == 0


def test_a_non_empty_foreign_database_is_refused_not_initialized() -> None:
    """Verify bootstrap refuses a database with tables Trace did not create, and mutates nothing."""
    from trace_core.core.errors import ApplicationError

    mgr = DatabaseSessionManager("sqlite:///:memory:")
    with mgr.engine.begin() as conn:
        conn.execute(sqlalchemy.text("CREATE TABLE someone_elses (id INTEGER)"))
        conn.execute(sqlalchemy.text("INSERT INTO someone_elses (id) VALUES (1)"))

    with pytest.raises(ApplicationError, match="Trace did not"):
        apply_migrations(mgr.engine)

    tables = get_table_names(mgr.engine)
    assert "schema_migrations" not in tables
    assert "someone_elses" in tables
    with mgr.engine.connect() as conn:
        assert conn.execute(sqlalchemy.text("SELECT id FROM someone_elses")).scalar() == 1


def test_migration_004_backfills_archived_by_on_old_database() -> None:
    """Stale schema self-heals on first use: no manual migrate needed."""

    from trace_core.cases.service import CaseService

    mgr = DatabaseSessionManager("sqlite:///:memory:")
    apply_migrations(mgr.engine)

    # Simulate a database migrated before archived_by existed.
    with mgr.engine.begin() as conn:
        conn.execute(sqlalchemy.text("ALTER TABLE cases DROP COLUMN archived_by"))
        conn.execute(sqlalchemy.text("DELETE FROM schema_migrations WHERE version = 4"))

    # First read heals the schema automatically (the old `case list` failure is gone).
    service = CaseService(mgr)
    assert service.list_cases() == []
    assert get_pending_migrations(mgr.engine) == []


def test_unit_of_work_transaction_and_hooks() -> None:
    """Verify UnitOfWork executes post_commit_hooks on success and suppresses them on failure."""
    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    service = BaseService(mgr)

    hook_called = False

    def test_hook() -> None:
        nonlocal hook_called
        hook_called = True

    # Successful transaction
    with service.transaction() as uow:
        assert isinstance(uow, UnitOfWork)
        uow.on_commit(test_hook)

    assert hook_called is True

    # Mandatory before_commit failure must abort transaction and prevent post_commit execution
    pre_hook_called = False
    post_hook_called = False

    def failing_pre_hook(s: Any) -> None:
        nonlocal pre_hook_called
        pre_hook_called = True
        raise RuntimeError("Mandatory audit write failed")

    def suppressed_post_hook() -> None:
        nonlocal post_hook_called
        post_hook_called = True

    def failing_audit_transaction() -> None:
        with service.transaction() as uow:
            uow.before_commit(failing_pre_hook)
            uow.on_commit(suppressed_post_hook)

    with pytest.raises(RuntimeError, match="Mandatory audit write failed"):
        failing_audit_transaction()

    assert pre_hook_called is True
    assert post_hook_called is False


@pytest.fixture
def sqlite_file_manager(tmp_path):  # type: ignore[no-untyped-def]
    """File-backed SQLite manager for thread/lock tests (:memory: cannot cross threads)."""
    mgr = DatabaseSessionManager(f"sqlite:///{tmp_path / 'test.db'}")
    mgr.init_schema()
    return mgr


def test_mask_db_url_with_special_char_password() -> None:
    """Verify passwords containing @/: survive masking without leaking fragments."""
    from trace_core.core.database.session import sanitized_db_url as _mask_db_url

    masked = _mask_db_url("postgresql+psycopg://bob:p%40ss:w0rd@localhost:5432/trace")
    assert "p%40ss" not in masked
    assert "w0rd" not in masked
    assert masked.startswith("postgresql+psycopg://bob:*****@")
    assert masked.endswith("/trace")
    assert _mask_db_url("sqlite:///trace.db") == "sqlite:///trace.db"


def _attempt_tamper_write(session, stmt: str) -> None:  # type: ignore[no-untyped-def]
    """Execute a tamper statement and flush. Single throwing call for narrow raises blocks."""
    from sqlalchemy import text

    session.execute(text(stmt))
    session.flush()


def test_migration_008_audit_append_only(sqlite_file_manager) -> None:  # type: ignore[no-untyped-def]
    """Verify 008 installs ledger triggers and writes/updates are rejected (parity row 1)."""
    from sqlalchemy import text

    engine = sqlite_file_manager.engine
    rows = (
        engine.connect()
        .execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit_events'"))
        .fetchall()
    )
    assert {"audit_events_no_update", "audit_events_no_delete"} <= {r[0] for r in rows}

    from sqlalchemy.exc import DBAPIError

    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    CaseService(sqlite_file_manager).create_case(CaseCreateDto(title="T", lead_examiner="E"))

    with sqlite_file_manager.session() as session:
        with pytest.raises(DBAPIError):
            _attempt_tamper_write(session, "UPDATE audit_events SET actor = 'mallory'")
        session.rollback()
        with pytest.raises(DBAPIError):
            _attempt_tamper_write(session, "DELETE FROM audit_events")
        session.rollback()


def test_migrations_concurrent_bootstrap_single_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Verify two processes bootstrapping at once apply migrations exactly once (R8)."""
    from concurrent.futures import ThreadPoolExecutor

    from trace_core.core.database.migrations import get_applied_migrations

    url = f"sqlite:///{tmp_path / 'race.db'}"

    def bootstrap() -> list[str]:
        from trace_core.core.database.migrations import apply_migrations

        mgr = DatabaseSessionManager(url)
        return apply_migrations(mgr.engine)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: bootstrap(), range(2)))

    # Exactly-once ledger rows regardless of who won the race.
    versions = sorted(m["version"] for m in get_applied_migrations(DatabaseSessionManager(url).engine))
    from trace_core.core.database.migrations import MIGRATIONS

    assert versions == sorted(version for version, _, _ in MIGRATIONS)


def test_audit_head_serializes_under_threads(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Verify concurrent appends serialize into a contiguous chain (parity row 2)."""
    from concurrent.futures import ThreadPoolExecutor

    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    mgr = DatabaseSessionManager(f"sqlite:///{tmp_path / 'chain.db'}")
    mgr.init_schema()
    svc = CaseService(mgr)

    def make_case(i: int) -> None:
        # Single-writer contract: SQLite serializes writers; losers retry the
        # whole transaction (PostgreSQL serializes via row locks instead).
        for _ in range(20):
            try:
                CaseService(mgr).create_case(CaseCreateDto(title=f"Race {i}", lead_examiner="Ex"))
                return
            except Exception:
                continue
        raise AssertionError(f"case {i} never committed")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(make_case, range(10)))

    assert len(svc.list_cases()) == 10
    res = AuditService(mgr).verify()
    assert res.is_valid
    assert (res.first_seq, res.last_seq, res.events_verified) == (1, 10, 10)


def test_sql_echo_decoupled_from_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify SQL echo follows TRACE_SQL_ECHO, never debug (S4)."""
    from trace_core.core.settings import settings

    assert settings.sql_echo is False
    assert DatabaseSessionManager("sqlite:///:memory:").engine.echo is False
    monkeypatch.setattr(settings, "debug", True)
    assert DatabaseSessionManager("sqlite:///:memory:").engine.echo is False
    monkeypatch.setattr(settings, "sql_echo", True)
    assert DatabaseSessionManager("sqlite:///:memory:").engine.echo is True


def test_version_single_sourced() -> None:
    """Verify settings.version tracks pyproject.toml (single source of truth)."""
    import tomllib
    from pathlib import Path

    import trace_core
    from trace_core.core.settings import settings

    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_bytes().decode("utf-8"))
    assert settings.version == pyproject["project"]["version"]
    assert trace_core.__version__ == pyproject["project"]["version"]


def test_update_channel_literal_matches_update_channel_enum() -> None:
    """Verify the settings channel Literal and the UpdateChannel enum agree."""
    from typing import get_args

    from trace_core.core.settings import Settings
    from trace_core.updates.domain import UpdateChannel

    literal_values = set(get_args(Settings.model_fields["update_channel"].annotation))
    assert literal_values == {channel.value for channel in UpdateChannel}


def test_cli_db_commands(monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager) -> None:
    """Verify trace db status, init, and migrate CLI commands."""
    monkeypatch.setattr("trace_core.core.cli.db_commands.db_manager", session_manager)
    runner = CliRunner()

    # db status
    status_res = runner.invoke(app, ["db", "status"])
    assert status_res.exit_code == 0
    assert "Trace Database Status" in status_res.output
    assert "Online" in status_res.output
    assert "Schema Migrations" in status_res.output

    # db migrate (already migrated)
    migrate_res = runner.invoke(app, ["db", "migrate"])
    assert migrate_res.exit_code == 0
    assert "up to date" in migrate_res.output.lower()

    # db init
    init_res = runner.invoke(app, ["db", "init"])
    assert init_res.exit_code == 0
    assert "database schema initialized" in init_res.output.lower()


def test_snapshot_shows_checked_database_url(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Health snapshot displays the manager under test, not the global settings URL."""
    from trace_core.core.database.health import fetch_db_snapshot
    from trace_core.core.database.session import DatabaseSessionManager

    mgr = DatabaseSessionManager(f"sqlite:///{tmp_path}/other-place.db")
    snap = fetch_db_snapshot(mgr)
    assert snap.healthy is True
    assert "other-place.db" in snap.masked_url


@pytest.fixture
def verified_case(session_manager: DatabaseSessionManager):
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    return CaseService(session_manager).create_case(CaseCreateDto(title="Verifier", lead_examiner="Ex"))


def test_sqlite_connections_use_immediate_isolation_and_wait_for_the_lock(tmp_path) -> None:
    from trace_core.core.database.session import create_db_engine

    engine = create_db_engine(f"sqlite:///{tmp_path / 'pragma.db'}")
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
            fairy = conn.connection
            assert fairy is not None
            raw = fairy.dbapi_connection
            assert raw is not None
            assert raw.isolation_level == "IMMEDIATE"
    finally:
        engine.dispose()


def test_the_case_check_verifier_reads_the_rows_on_sqlite(session_manager, verified_case) -> None:
    from sqlalchemy import text as sa_text

    from trace_core.core.database.migrations import _verify_006_case_checks

    with session_manager.engine.begin() as conn:
        assert _verify_006_case_checks(conn) is True
        conn.execute(sa_text("UPDATE cases SET version = 0 WHERE number = :number"), {"number": verified_case.number})
        assert _verify_006_case_checks(conn) is False


def test_migration_023_refuses_duplicates_then_adds_the_unique_index_after_cleanup(tmp_path) -> None:
    mgr = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'dup.db').as_posix()}")
    apply_migrations(mgr.engine)
    with mgr.engine.begin() as conn:
        conn.execute(sqlalchemy.text("DROP INDEX uq_anchor_intents_case_seq"))
        conn.execute(sqlalchemy.text("DELETE FROM schema_migrations WHERE version = 23"))
        for row_id, chain, created in (
            ("00000000000000000000000000000001", "a", "2026-01-01 00:00:00.000000+00:00"),
            ("00000000000000000000000000000002", "b", "2026-01-02 00:00:00.000000+00:00"),
        ):
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO anchor_intents (id, case_number, seq, chain_hash, status, attempt_count, created_at) "
                    "VALUES (:id, '2026-DUP-0001', 7, :chain, 'pending', 0, :created)"
                ),
                {"id": row_id, "chain": chain, "created": created},
            )
    with pytest.raises(RuntimeError, match=r"2026-DUP-0001 seq 7 x2"):
        apply_migrations(mgr.engine)
    with mgr.engine.connect() as conn:
        kept = conn.execute(
            sqlalchemy.text("SELECT chain_hash, status FROM anchor_intents WHERE case_number = '2026-DUP-0001'")
        ).fetchall()
        recorded = conn.execute(sqlalchemy.text("SELECT count(*) FROM schema_migrations WHERE version = 23")).scalar()
    assert sorted(kept) == [("a", "pending"), ("b", "pending")]
    assert recorded == 0
    with mgr.engine.begin() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM anchor_intents WHERE id = '00000000000000000000000000000001'"))
    applied = apply_migrations(mgr.engine)
    assert "023_anchor_intents_unique_position" in applied
    with mgr.engine.connect() as conn:
        remaining = conn.execute(
            sqlalchemy.text("SELECT chain_hash, status FROM anchor_intents WHERE case_number = '2026-DUP-0001'")
        ).fetchall()
    assert remaining == [("b", "pending")]
    inspector = sqlalchemy.inspect(mgr.engine)
    assert "uq_anchor_intents_case_seq" in {index["name"] for index in inspector.get_indexes("anchor_intents")}


def test_a_decommissioned_migration_is_recorded_without_running(tmp_path) -> None:
    from trace_core.core.database import migrations as mig

    probe_version = len(mig.MIGRATIONS) + 1
    probe_name = f"{probe_version}_test_decommissioned_probe"
    ran: list[bool] = []

    @mig.register_migration(probe_version, probe_name, operations=("test:decommissioned_probe",), decommissioned=True)
    def _probe(bind):  # type: ignore[no-untyped-def]
        ran.append(True)

    try:
        mgr = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'decommissioned.db').as_posix()}")
        applied = apply_migrations(mgr.engine)
        assert probe_name in applied
        assert ran == []
        assert probe_version in {record["version"] for record in get_applied_migrations(mgr.engine)}
    finally:
        mig.MIGRATIONS[:] = [m for m in mig.MIGRATIONS if m[1] != probe_name]
        mig.DECOMMISSIONED_MIGRATIONS.discard(probe_version)
        mig.MIGRATION_VERIFIERS.pop(probe_version, None)
        mig.MIGRATION_OPERATIONS.pop(probe_version, None)


def test_migration_011_is_decommissioned_with_a_resilient_replacement() -> None:
    from trace_core.core.database import migrations as mig

    assert 11 in mig.DECOMMISSIONED_MIGRATIONS
    names = {version: name for version, name, _ in mig.MIGRATIONS}
    assert names.get(25) == "025_least_privilege_roles_resilient"

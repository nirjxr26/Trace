"""Tests for database lifecycle, connection health checks, migrations, and CLI db commands."""

from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy
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
            s = Settings()
            assert s is not None
            mock_warning.assert_called_once()


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


def test_migration_004_backfills_archived_by_on_old_database() -> None:
    """Reproduce stale-schema failure: DB migrated before archived_by existed must self-heal."""

    from trace_core.cases.service import CaseService

    mgr = DatabaseSessionManager("sqlite:///:memory:")
    apply_migrations(mgr.engine)

    # Simulate a database migrated before archived_by existed.
    with mgr.engine.begin() as conn:
        conn.execute(sqlalchemy.text("ALTER TABLE cases DROP COLUMN archived_by"))
        conn.execute(sqlalchemy.text("DELETE FROM schema_migrations WHERE version = 4"))

    # Stale schema breaks reads touching the new column (the reported `case list` failure).
    service = CaseService(mgr)
    with pytest.raises(sqlalchemy.exc.OperationalError):
        service.list_cases()

    # Pending migration heals the schema; reads work again.
    assert (4, "004_add_archived_by_column") in get_pending_migrations(mgr.engine)
    assert apply_migrations(mgr.engine) == ["004_add_archived_by_column"]
    assert service.list_cases() == []


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


def test_cli_db_commands(monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager) -> None:
    """Verify trace db status, init, and migrate CLI commands."""
    monkeypatch.setattr("trace_core.core.cli.db_commands.db_manager", session_manager)
    runner = CliRunner()

    # db status
    status_res = runner.invoke(app, ["db", "status"])
    assert status_res.exit_code == 0
    assert "Trace Database Status" in status_res.output
    assert "Online" in status_res.output
    assert "cases" in status_res.output

    # db migrate (already migrated)
    migrate_res = runner.invoke(app, ["db", "migrate"])
    assert migrate_res.exit_code == 0
    assert "already up to date" in migrate_res.output.lower()

    # db init
    init_res = runner.invoke(app, ["db", "init"])
    assert init_res.exit_code == 0
    assert "initialized successfully" in init_res.output.lower()

"""Unit tests for trace doctor preflight diagnostics."""

import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit


def test_doctor_healthy(monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager) -> None:
    """Verify doctor exits 0 with all PASS rows on a migrated database."""
    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", session_manager)
    res = CliRunner().invoke(app, ["doctor"])
    assert res.exit_code == 0
    assert "Trace Doctor" in res.output
    assert "PASS" in res.output
    assert "FAIL" not in res.output


def test_doctor_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify doctor exits 1 with FAIL rows and remediation when DB is down."""
    import sqlalchemy.exc

    bad_mgr = DatabaseSessionManager("sqlite:///:memory:")

    def _boom() -> None:
        raise sqlalchemy.exc.OperationalError("connect", None, Exception("connection refused"))

    monkeypatch.setattr(bad_mgr, "ensure_ready", _boom)
    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", bad_mgr)
    res = CliRunner().invoke(app, ["doctor"])
    assert res.exit_code == 1
    assert "FAIL" in res.output
    assert "trace doctor" in res.output


def test_doctor_pending_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify doctor self-heals a fresh schema (no manual migrate needed)."""
    fresh_mgr = DatabaseSessionManager("sqlite:///:memory:")
    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", fresh_mgr)
    res = CliRunner().invoke(app, ["doctor"])
    assert res.exit_code == 0
    assert "up to date" in res.output.lower()
    assert "FAIL" not in res.output

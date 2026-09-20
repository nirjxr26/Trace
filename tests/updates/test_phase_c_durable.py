import hashlib

import pytest

from trace_core.updates.errors import RecoveryError

pytestmark = pytest.mark.unit


def test_migration_marker_renamed(temp_storage_root):
    from trace_core.updates import marker as result_marker
    from trace_core.updates import migration as migration_mod

    assert migration_mod.migration_marker_path().name == "update-active.json"
    assert result_marker.marker_path().name == "update-result.json"
    assert migration_mod.migration_marker_path() != result_marker.marker_path()


def test_transition_failure_keeps_state(session_manager, temp_storage_root, monkeypatch):
    from trace_core.updates.domain import UpdateState
    from trace_core.updates.lifecycle import UpdateLifecycle
    from trace_core.updates.service import UpdateService

    def _boom(data):
        raise OSError("disk full")

    import trace_core.updates.marker as marker_mod

    monkeypatch.setattr(marker_mod, "write_marker", _boom)
    life = UpdateLifecycle("tx-c-state", UpdateService(session_manager))
    with pytest.raises(OSError):
        life.transition(UpdateState.CHECKING)
    assert life.state == UpdateState.IDLE


def test_schema_keys_versioned():
    from trace_core.updates.marker import MARKER_SCHEMA, REQUIRED_KEYS, SCHEMA_REQUIRED_KEYS

    assert SCHEMA_REQUIRED_KEYS[MARKER_SCHEMA] == REQUIRED_KEYS
    assert set(REQUIRED_KEYS) == {"marker_schema", "transaction_id", "state"}


def test_pre_mutation_failure_cleans_backup(temp_storage_root, tmp_path):
    from trace_core.core.database.session import DatabaseSessionManager
    from trace_core.updates.errors import MigrationCompatibilityError
    from trace_core.updates.migration import marker_state

    mgr = DatabaseSessionManager(f"sqlite:///{tmp_path}/orphan-src.db")
    mgr.init_schema()
    backup_dir = tmp_path / "backups"
    with pytest.raises(MigrationCompatibilityError):
        from trace_core.updates.migration import run_updater_migration

        run_updater_migration(mgr, "tx-orphan-1", schema_min=9999, backup_dir=backup_dir)
    assert not (backup_dir / "trace-backup.db").exists()
    assert marker_state() == ("absent", None)


def test_corrupt_marker_tx_deterministic(session_manager, temp_storage_root):
    from trace_core.updates.migration import migration_marker_path
    from trace_core.updates.service import UpdateService

    raw = b"{not-json"
    migration_marker_path().parent.mkdir(parents=True, exist_ok=True)
    migration_marker_path().write_bytes(raw)
    from trace_core.core.cli.recovery import _triage_update_marker

    svc = UpdateService(session_manager)
    _triage_update_marker(svc)
    expected = "corrupt-" + hashlib.sha256(raw).hexdigest()[:12]
    rows = svc.list_history()
    assert any(r.transaction_id == expected and r.failure_stage == "recovery" for r in rows)


def test_service_read_delegates(temp_storage_root, tmp_path, session_manager):
    from trace_core.updates.marker import write_marker
    from trace_core.updates.service import UpdateService

    svc = UpdateService(session_manager)
    assert svc.read_result_marker() is None
    write_marker({"transaction_id": "t-del", "state": "FAILED"})
    data = svc.read_result_marker()
    assert data is not None
    assert data["transaction_id"] == "t-del"
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert svc.read_result_marker(bad) is None


def test_recovery_blocked_exit_16(temp_storage_root):
    import threading

    from typer.testing import CliRunner

    from trace_core.cli.main import app
    from trace_core.updates.lock import update_lock

    ready = threading.Event()
    done = threading.Event()

    def _hold():
        with update_lock():
            ready.set()
            done.wait(timeout=30)

    thread = threading.Thread(target=_hold, daemon=True)
    thread.start()
    assert ready.wait(timeout=10)
    try:
        from trace_core.updates.migration import begin_update_migration, finish_update_migration

        begin_update_migration("tx-blocked-1")
        try:
            res = CliRunner().invoke(app, ["recovery"])
        finally:
            finish_update_migration("tx-blocked-1")
        assert res.exit_code == 16
    finally:
        done.set()
        thread.join(timeout=10)


def test_unknown_schema_still_fails_closed(temp_storage_root, tmp_path):
    import json

    from trace_core.updates.marker import read_marker

    path = tmp_path / "m.json"
    path.write_text(json.dumps({"marker_schema": 999, "transaction_id": "t", "state": "IDLE"}), encoding="utf-8")
    with pytest.raises(RecoveryError):
        read_marker(path)

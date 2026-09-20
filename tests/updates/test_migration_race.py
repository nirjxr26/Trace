import pytest

from trace_core.updates.errors import MigrationCompatibilityError, UpdateInProgressError
from trace_core.updates.migration import (
    begin_update_migration,
    current_schema_version,
    finish_update_migration,
    run_updater_migration,
    verify_compatibility,
)


def test_ensure_ready_blocked_during_update(session_manager, temp_storage_root):
    begin_update_migration("tx-race-1")
    try:
        with pytest.raises(UpdateInProgressError):
            session_manager.ensure_ready()
    finally:
        finish_update_migration("tx-race-1")
    session_manager.ensure_ready()


def test_updater_migration_clears_marker(session_manager, temp_storage_root):
    result = run_updater_migration(session_manager, "tx-mig-1")
    assert result["schema"] == current_schema_version(session_manager)
    from trace_core.updates.migration import marker_state

    assert marker_state() == ("absent", None)


def test_corrupt_marker_fails_closed(session_manager, temp_storage_root):
    from trace_core.updates.migration import marker_path, marker_state

    marker_path().parent.mkdir(parents=True, exist_ok=True)
    marker_path().write_text("{not-json", encoding="utf-8")
    assert marker_state()[0] == "corrupt"
    with pytest.raises(UpdateInProgressError):
        session_manager.ensure_ready()
    marker_path().unlink(missing_ok=True)


def test_recovery_clears_stale_marker(session_manager, temp_storage_root):
    from typer.testing import CliRunner

    from trace_core.cli.main import app
    from trace_core.updates.migration import marker_state

    begin_update_migration("tx-stale-1")
    assert marker_state()[0] == "active"
    res = CliRunner().invoke(app, ["recovery"])
    assert res.exit_code == 0
    assert marker_state() == ("absent", None)
    session_manager.ensure_ready()


def test_compat_rejects_below_minimum(session_manager, temp_storage_root):
    current = current_schema_version(session_manager)
    with pytest.raises(MigrationCompatibilityError):
        verify_compatibility(session_manager, current + 100, None)


def test_backup_failure_blocks_migration(session_manager, temp_storage_root, tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run_updater_migration(session_manager, "tx-backup-1", backup_required=True, backup_dir=blocker)
    from trace_core.updates.migration import marker_state

    assert marker_state() == ("absent", None)


def test_rollback_refuses_missing_metadata(session_manager, temp_storage_root, tmp_path):
    from trace_core.updates.errors import RecoveryError
    from trace_core.updates.migration import rollback_release
    from trace_updater import updater as updater_mod

    base = tmp_path / "install"
    for version, payload in (("0.1.0", b"good"), ("0.2.0", b"bad")):
        seed = tmp_path / f"seed-{version}"
        seed.mkdir()
        (seed / "trace.bin").write_bytes(payload)
        updater_mod.stage_release(seed, base, version, expected=["trace.bin"])
        updater_mod.activate(base, version)
    with pytest.raises(RecoveryError):
        rollback_release(base, session_manager, None)


def test_rollback_refuses_incompatible_schema(session_manager, temp_storage_root, tmp_path):
    from trace_core.updates.errors import RecoveryError
    from trace_core.updates.migration import rollback_release
    from trace_updater import updater as updater_mod

    base = tmp_path / "install"
    for version, payload in (("0.1.0", b"good"), ("0.2.0", b"bad")):
        seed = tmp_path / f"seed-{version}"
        seed.mkdir()
        (seed / "trace.bin").write_bytes(payload)
        updater_mod.stage_release(
            seed, base, version, expected=["trace.bin"], release_meta={"version": version, "schema_min": 9999}
        )
        updater_mod.activate(base, version)
    with pytest.raises(RecoveryError):
        rollback_release(base, session_manager, None)


def test_noncontiguous_schema_rejected(session_manager, temp_storage_root):
    from sqlalchemy import text

    from trace_core.updates.errors import MigrationCompatibilityError
    from trace_core.updates.migration import current_schema_version

    with session_manager.engine.begin() as conn:
        conn.execute(text("DELETE FROM schema_migrations WHERE version = 3"))
    with pytest.raises(MigrationCompatibilityError):
        current_schema_version(session_manager)


def test_backup_default_on_for_schema_advance(session_manager, temp_storage_root, tmp_path):
    from trace_core.updates.migration import run_updater_migration

    with pytest.raises(Exception, match="backup required but no backup directory"):
        run_updater_migration(session_manager, "tx-defbackup-1", schema_min=1, schema_target=9999)


def test_waiver_skips_backup_but_records(session_manager, temp_storage_root, tmp_path):
    from trace_core.updates.errors import MigrationCompatibilityError
    from trace_core.updates.migration import run_updater_migration

    with pytest.raises(MigrationCompatibilityError):
        run_updater_migration(
            session_manager, "tx-waive-1", schema_min=1, schema_target=9999, backup_waiver="lab device, no space"
        )
    from trace_core.updates.migration import marker_state

    assert marker_state() == ("absent", None)


def test_concurrent_entry_points_serialize(temp_storage_root, tmp_path):
    import threading

    from trace_updater import updater as updater_mod

    base = tmp_path / "install"
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "trace.bin").write_bytes(b"x")
    updater_mod.stage_release(seed, base, "9.9.9", expected=["trace.bin"])
    errors = []

    def _activate():
        try:
            updater_mod.activate(base, "9.9.9")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_activate) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert updater_mod.read_active(base) == "9.9.9"


def test_sqlite_backup_roundtrip(temp_storage_root, tmp_path):
    from trace_core.core.database.session import DatabaseSessionManager
    from trace_core.updates.migration import backup_database

    mgr = DatabaseSessionManager(f"sqlite:///{tmp_path}/backup-src.db")
    mgr.init_schema()
    out = backup_database(mgr, tmp_path / "backups")
    assert out.exists()
    assert out.stat().st_size > 0

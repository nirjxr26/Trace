"""Restoring a SQLite database has three ways to go wrong, all of them silent before.

Trace sets journal_mode=WAL on every connection, so committed rows can live only in
`trace.db-wal`. The old restore copied the backup over `trace.db` and left the old WAL
beside it, disposed only the engine of the one manager passed in, and never checked that
the result was a database at all.

These use a real file-backed SQLite database, not :memory: — the branch under test cannot
be reached with :memory:.
"""

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def live_db(tmp_path):
    path = tmp_path / "trace.db"
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE audit_events (seq INTEGER PRIMARY KEY, note TEXT)")
    conn.execute("INSERT INTO audit_events (seq, note) VALUES (1, 'kept')")
    conn.close()
    return path


def _manager_for(path):
    from trace_core.core.database.session import DatabaseSessionManager

    return DatabaseSessionManager(f"sqlite:///{path.as_posix()}")


def _backup_in_storage(tmp_path, name):
    """Backups are confined to the storage root, so a test backup has to live there.

    Named after the test's own directory: the storage root is shared across tests, so a
    fixed name would collide.
    """
    from trace_core.core.settings import settings

    dest = Path(settings.storage_root) / "backups" / f"{tmp_path.name}_{name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    return dest


def _sidecars(path):
    return [path.with_name(path.name + s) for s in ("-wal", "-shm")]


def test_wal_sidecars_do_not_survive_a_restore(live_db, tmp_path) -> None:
    """A stale WAL beside a freshly copied main file is the old database's transaction
    log. SQLite may discard it or replay it; neither is acceptable."""
    from trace_core.updates.migration import restore_backup

    backup = _backup_in_storage(tmp_path, "backup.db")
    b = sqlite3.connect(backup)
    b.execute("CREATE TABLE audit_events (seq INTEGER PRIMARY KEY, note TEXT)")
    b.execute("INSERT INTO audit_events (seq, note) VALUES (1, 'from backup')")
    b.commit()
    b.close()

    # SQLite removes the sidecars when the last connection closes, so plant them: what
    # matters is that the restore clears them whatever produced them.
    for sidecar in _sidecars(live_db):
        sidecar.write_bytes(b"stale write-ahead log from the previous database")

    restore_backup(backup, _manager_for(live_db))

    for sidecar in _sidecars(live_db):
        assert not sidecar.exists(), f"{sidecar.name} survived the restore"
    conn = sqlite3.connect(live_db)
    rows = conn.execute("SELECT note FROM audit_events").fetchall()
    conn.close()
    assert rows == [("from backup",)], rows


def test_a_corrupt_backup_never_replaces_the_live_database(live_db, tmp_path) -> None:
    """The old code copied first and checked nothing. A truncated or non-SQLite backup
    would overwrite a healthy evidence database and only be discovered later."""
    from trace_core.updates.errors import RecoveryError
    from trace_core.updates.migration import restore_backup

    bad = _backup_in_storage(tmp_path, "bad.db")
    bad.write_bytes(b"this is not a database")

    with pytest.raises(RecoveryError):
        restore_backup(bad, _manager_for(live_db))

    conn = sqlite3.connect(live_db)
    rows = conn.execute("SELECT note FROM audit_events").fetchall()
    conn.close()
    assert ("kept",) in rows, f"the live database was damaged: {rows}"


def test_a_restore_that_cannot_be_verified_says_the_current_database_is_intact(live_db, tmp_path) -> None:
    from trace_core.updates.errors import RecoveryError
    from trace_core.updates.migration import restore_backup

    bad = _backup_in_storage(tmp_path, "bad.db")
    bad.write_bytes(b"not a database either")
    with pytest.raises(RecoveryError) as caught:
        restore_backup(bad, _manager_for(live_db))
    message = str(caught.value).lower()
    assert "left in place" in message or "current database" in message, message


def test_no_staging_file_is_left_behind(live_db, tmp_path) -> None:
    from trace_core.updates.errors import RecoveryError
    from trace_core.updates.migration import restore_backup

    bad = _backup_in_storage(tmp_path, "bad.db")
    bad.write_bytes(b"nope")
    with pytest.raises(RecoveryError):
        restore_backup(bad, _manager_for(live_db))

    leftovers = list(live_db.parent.glob(f"{live_db.name}*"))
    names = {p.name for p in leftovers}
    assert live_db.name in names, names
    assert not any(".restore" in n for n in names), f"staging file left behind: {names}"

import contextlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from trace_core.core.database.session import DatabaseSessionManager, sqlite_file_path
from trace_core.core.fs import JsonFileVerdict, atomic_write_lines, check_contained, classify_json_file, sqlite_sidecars
from trace_core.updates.errors import (
    MigrationCompatibilityError,
    RecoveryError,
    UpdateError,
    UpdateInProgressError,
)

_PG_RESTORE_TIMEOUT_SECONDS = 600
_PG_BACKUP_TIMEOUT_SECONDS = 300
_BACKUP_FAILED = "database backup failed"
BACKUP_PATH_REFUSED = "backup path refused; cannot restore"


def migration_marker_path() -> Path:
    from trace_core.updates.marker import storage_state_path

    return storage_state_path("update-active.json")


_local = threading.local()


def _ambient_tx() -> str | None:
    return getattr(_local, "tx", None)


def update_migration_owner(transaction_id: str):  # type: ignore[no-untyped-def]
    from contextlib import contextmanager

    @contextmanager
    def _owner():  # type: ignore[no-untyped-def]
        previous = getattr(_local, "tx", None)
        _local.tx = transaction_id
        try:
            yield
        finally:
            if previous is None:
                try:
                    del _local.tx
                except AttributeError:
                    pass
            else:
                _local.tx = previous

    return _owner()


def is_owner(transaction_id: str) -> bool:
    # Thread-local is the authority for "am I the owner" — the marker file
    # only says an update is active, not who is asking. Callers running a
    # transaction in another thread must propagate it via
    # update_migration_owner() (run_updater_migration does this itself).
    return _ambient_tx() == transaction_id


def marker_state() -> tuple[str, dict | None]:
    """Single classifier for the migration marker. Four callers used to classify the same
    OSError three different ways — "corrupt" (marker.py), "unreadable" (session.py) and
    "corrupt" again (here) — and only one of those names lets an operator act correctly.
    A file that cannot be read is not corrupt, and must not be deleted as if it were.

    States: absent · active · corrupt (readable but unusable) · unreadable (could not be read).
    """
    p = migration_marker_path()
    if not p.exists():
        return "absent", None
    verdict, data = classify_json_file(p)
    if verdict is JsonFileVerdict.UNREADABLE:
        return "unreadable", None
    if verdict is not JsonFileVerdict.OK or data is None or "transaction_id" not in data:
        return "corrupt", None
    return "active", data


def begin_update_migration(transaction_id: str) -> None:
    target = migration_marker_path()
    atomic_write_lines(target, [json.dumps({"transaction_id": transaction_id})])


def finish_update_migration(transaction_id: str) -> None:
    state, active = marker_state()
    if state == "active" and active is not None and active.get("transaction_id") != transaction_id:
        raise UpdateInProgressError("another update transaction owns migration")
    migration_marker_path().unlink(missing_ok=True)


def applied_versions(manager: DatabaseSessionManager) -> list[int]:
    from trace_core.core.database.migrations import get_applied_migrations

    return sorted(m["version"] for m in get_applied_migrations(manager.engine))


def current_schema_version(manager: DatabaseSessionManager) -> int:
    applied = applied_versions(manager)
    highest = max(applied, default=0)
    if applied != list(range(1, highest + 1)):
        raise MigrationCompatibilityError(f"non-contiguous migrations applied: {applied}")
    return highest


def verify_compatibility(manager: DatabaseSessionManager, schema_min: int | None, schema_target: int | None) -> None:
    if (schema_min is None) != (schema_target is None):
        raise MigrationCompatibilityError("schema_min and schema_target must both be declared or both absent")
    current = current_schema_version(manager)
    if schema_min is not None and current < schema_min:
        raise MigrationCompatibilityError(f"schema {current} below minimum {schema_min}")
    if schema_target is not None and current > schema_target:
        raise MigrationCompatibilityError(f"schema {current} above target {schema_target}")


def _confine_backup_path(backup_path: str | Path) -> Path:
    from trace_core.core.settings import settings

    try:
        roots = [Path(settings.storage_root).resolve(), Path(settings.storage_root).parent.resolve()]
        resolved = Path(backup_path).resolve()
    except OSError:
        raise RecoveryError(BACKUP_PATH_REFUSED) from None
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise RecoveryError(BACKUP_PATH_REFUSED)
    return resolved


def _pg_env(password: str | None) -> dict[str, str]:
    """Subprocess environment for pg_dump/psql: ambient env plus PGPASSWORD when split out."""
    import os

    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    return env


def _pg_parts(url: str) -> tuple[str, str | None]:
    """Single source for PG URL split. Returns (passwordless_url, password_or_None). Never logs password."""
    base_scheme, _, base_rest = url.partition("://")
    drv, _, _ = base_scheme.partition("+")
    pg_url = drv + "://" + base_rest if base_rest else url
    scheme, _, rest = pg_url.partition("://")
    if not rest:
        return pg_url, None
    at = rest.rfind("@")
    if at == -1:
        return pg_url, None
    creds_host = rest
    creds, _, hostpart = creds_host.partition("@")
    if ":" not in creds:
        return pg_url, None
    user, _, password = creds.partition(":")
    if not password:
        return pg_url, None
    clean = f"{scheme}://{user}@{hostpart}"
    return clean, password


def sqlite3_usable(path: Path) -> bool:
    """Whether a restored file opens as a real SQLite database with an intact schema."""
    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return bool(row) and row[0] > 0
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()


def _checkpoint_sqlite(live: Path) -> None:
    """Fold the WAL into the main file and drop the sidecars.

    Trace sets journal_mode=WAL on every connection (session.py), so committed rows can sit
    only in `trace.db-wal`. Copying over `trace.db` while that file still exists restores the
    old main database and leaves the old transaction log beside it. Checkpointing first means
    the file being copied is the whole database.
    """
    import sqlite3

    try:
        conn = sqlite3.connect(live, isolation_level=None)
    except sqlite3.Error as e:
        raise RecoveryError(f"could not open the database to flush its write-ahead log ({e})") from e
    try:
        # PASSIVE, not TRUNCATE: TRUNCATE blocks while any other connection holds a read
        # lock, so a restore would hang on a database something else still has open. PASSIVE
        # folds in whatever it can and returns immediately. Anything left unflushed belongs
        # to the database being replaced, and the sidecars are removed after the swap.
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except sqlite3.Error:
        # Checkpointing is best-effort. Failing here would refuse a restore that can still
        # succeed, and the sidecar removal after the swap is what actually matters.
        pass
    finally:
        conn.close()


def _restore_sqlite(src: Path, live: Path, manager: DatabaseSessionManager) -> None:
    """Replace a SQLite database from a backup, keeping the current file if anything fails.

    Restores to a sibling first and verifies it, then swaps. A copy that fails partway leaves
    the live database untouched instead of half-overwritten.
    """
    if manager._engine is not None:
        manager._engine.dispose()
    if live.exists():
        _checkpoint_sqlite(live)
    staged = live.with_name(live.name + ".restore")
    try:
        shutil.copy2(src, staged)
        if sqlite3_usable(staged):
            if manager._engine is not None:
                manager._engine.dispose()
            os.replace(staged, live)
        else:
            raise RecoveryError("the restored database could not be opened; the current one was left in place")
    except OSError as e:
        raise RecoveryError(f"database restore failed ({e}); the current database was left in place") from e
    finally:
        for sidecar in sqlite_sidecars(staged):
            sidecar.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)
    for sidecar in sqlite_sidecars(live):
        sidecar.unlink(missing_ok=True)
    manager._engine = None
    manager._session_factory = None


def restore_backup(backup_path: str | Path, manager: DatabaseSessionManager) -> None:
    src = _confine_backup_path(backup_path)
    url = manager._url
    if not src.is_file() or src.stat().st_size == 0:
        raise RecoveryError("backup missing or empty; cannot restore")
    # Re-resolve after existence check to close symlink-swap TOCTOU.
    src = _confine_backup_path(src)
    try:
        fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        os.close(fd)
    except OSError as e:
        raise RecoveryError(BACKUP_PATH_REFUSED) from e
    live = sqlite_file_path(url)
    if live is not None:
        _restore_sqlite(src, live, manager)
        return
    if url.startswith("postgresql"):
        clean_url, password = _pg_parts(url)
        try:
            env = _pg_env(password)
            with src.open("rb") as handle:
                subprocess.run(
                    ["psql", clean_url, "-f", "-"],
                    stdin=handle,
                    stderr=subprocess.DEVNULL,
                    timeout=_PG_RESTORE_TIMEOUT_SECONDS,
                    check=True,
                    env=env,
                )
        except (OSError, subprocess.SubprocessError) as e:
            raise RecoveryError("database restore failed") from e
        return
    raise RecoveryError(f"restore unsupported for {url.split(':', 1)[0]}")


def rollback_release(base: str | Path, manager: DatabaseSessionManager, backup_path: str | Path | None) -> str:
    from trace_updater import updater as updater_mod

    previous = updater_mod.read_previous(base)
    if not previous:
        raise RecoveryError("no previous release to restore")
    meta = updater_mod.read_release_meta(base, previous)
    if meta is None:
        raise RecoveryError(f"previous release {previous} carries no compatibility metadata")
    schema_min = meta.get("schema_min")
    if schema_min is not None and current_schema_version(manager) < schema_min:
        if backup_path is None:
            raise RecoveryError(f"previous release {previous} requires schema >= {schema_min}; no backup recorded")
        restore_backup(backup_path, manager)
        if current_schema_version(manager) < schema_min:
            raise RecoveryError(f"previous release {previous} still incompatible after restore")
    # Code before pointer: reinstalling the retained wheel first means a pip
    # failure leaves the (failed) pointer untouched for RECOVERY_REQUIRED,
    # never a flipped pointer over stale code.
    from trace_core.updates import pip_backend

    try:
        pip_backend.restore_release(base, previous)
    except UpdateError as e:
        raise RecoveryError(f"previous release {previous} found but its code could not be reinstalled: {e}") from e
    failed = updater_mod.read_active(base)
    restored = updater_mod.rollback(base)
    _advance_previous(base, restored, failed)
    return restored


def _advance_previous(base: str | Path, restored: str | None, failed: str | None) -> None:
    """Retire the rolled-back release so a second recovery cannot repeat it.

    H-13: `previous-version` still named the release we just came *from*, so re-running
    `trace recovery` rolled back a second time to the same version. The failed release is
    now the current one, so it becomes the new `previous-version` — the file continues to
    mean "the release to return to if the next update fails", which is what rollback reads.
    """
    from trace_core.core.fs import atomic_write_lines
    from trace_updater.updater import previous_path

    if not restored or not failed or failed == restored:
        return
    atomic_write_lines(previous_path(base), [failed])


def _unique_stamp(dest: Path) -> str:
    """Second-resolution timestamp, disambiguated if two backups land in the same second.

    A bare timestamp is not uniqueness: two updates inside one second reused the name, and
    SQLite's `VACUUM INTO` refuses an existing file, so the second backup still failed.
    """
    from trace_core.core.clock import now_utc

    base = now_utc().strftime("%Y%m%dT%H%M%SZ")
    if not any(dest.glob(f"trace-backup-{base}*")):
        return base
    for n in range(2, 100):
        candidate = f"{base}-{n}"
        if not any(dest.glob(f"trace-backup-{candidate}*")):
            return candidate
    raise UpdateError(_BACKUP_FAILED)


def backup_database(manager: DatabaseSessionManager, dest_dir: str | Path) -> Path:
    from sqlalchemy import text

    from trace_core.core.fs import ensure_dir

    url = manager._url
    dest = ensure_dir(dest_dir)
    stamp = _unique_stamp(dest)
    if url.startswith("sqlite") and ":memory:" not in url:
        out = dest / f"trace-backup-{stamp}.db"
        literal = str(check_contained(out, dest)).replace("'", "''")
        with manager.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"VACUUM INTO '{literal}'"))
        if not out.is_file() or out.stat().st_size == 0:
            raise UpdateError(f"{_BACKUP_FAILED}: empty backup")
        return out
    if url.startswith("postgresql"):
        out = dest / f"trace-backup-{stamp}.sql"
        check_contained(out, dest)
        clean_url, password = _pg_parts(url)
        try:
            env = _pg_env(password)
            with out.open("wb") as handle:
                subprocess.run(
                    ["pg_dump", clean_url],
                    stdout=handle,
                    stderr=subprocess.DEVNULL,
                    timeout=_PG_BACKUP_TIMEOUT_SECONDS,
                    check=True,
                    env=env,
                )
        except (OSError, subprocess.SubprocessError) as e:
            raise UpdateError(_BACKUP_FAILED) from e
        if out.stat().st_size == 0:
            raise UpdateError(f"{_BACKUP_FAILED}: empty dump")
        return out
    raise UpdateError(f"backup unsupported for {url.split(':', 1)[0]}")


def run_updater_migration(
    manager: DatabaseSessionManager,
    transaction_id: str,
    schema_min: int | None = None,
    schema_target: int | None = None,
    backup_required: bool = False,
    backup_dir: str | Path | None = None,
    backup_waiver: str | None = None,
) -> dict:
    state, active = marker_state()
    if state == "unreadable":
        raise UpdateInProgressError("update marker unreadable; left in place, run trace recovery before migrating")
    if state == "corrupt":
        raise UpdateInProgressError("update marker corrupt; run trace recovery before migrating")
    if state == "active" and active is not None and active.get("transaction_id") != transaction_id:
        raise UpdateInProgressError("another update transaction owns migration")
    # H-17: when a caller already owns this transaction — the lifecycle does, for the
    # whole update — it owns the marker too. Clearing it here dropped the "an update
    # owns migrations" signal before health check, activation, retention prune, history
    # and the result marker, leaving only update_lock() protecting that window.
    caller_owns = is_owner(transaction_id)
    if not caller_owns:
        begin_update_migration(transaction_id)
    try:
        with update_migration_owner(transaction_id):
            return _run_updater_migration_locked(
                manager,
                transaction_id,
                schema_min=schema_min,
                schema_target=schema_target,
                backup_required=backup_required,
                backup_dir=backup_dir,
                backup_waiver=backup_waiver,
            )
    finally:
        # A caller-owned marker is released by whoever reached a terminal state.
        if not caller_owns:
            with contextlib.suppress(UpdateInProgressError):
                finish_update_migration(transaction_id)


def _run_updater_migration_locked(
    manager: DatabaseSessionManager,
    transaction_id: str,
    schema_min: int | None = None,
    schema_target: int | None = None,
    backup_required: bool = False,
    backup_dir: str | Path | None = None,
    backup_waiver: str | None = None,
) -> dict:
    from trace_core.core.database.migrations import apply_migrations, verify_migration_checksums

    backup_path = None
    mutated = False
    try:
        current = current_schema_version(manager)
        would_advance = schema_target is not None and schema_target > current
        needs_backup = backup_required or (would_advance and backup_waiver is None)
        if needs_backup:
            if backup_dir is None:
                raise UpdateError("backup required but no backup directory given")
            backup_path = backup_database(manager, backup_dir)
        verify_compatibility(manager, schema_min, schema_target)
        mutated = True
        applied = apply_migrations(manager.engine)
        verify_migration_checksums(manager.engine)
        after = current_schema_version(manager)
        if schema_target is not None and after < schema_target:
            raise MigrationCompatibilityError(f"schema {after} below target {schema_target}")
        result = {
            "applied": applied,
            "schema": after,
            "backup": str(backup_path) if backup_path else None,
            "backup_waived": backup_waiver if (would_advance and backup_path is None) else None,
        }
    except Exception:
        if backup_path is not None and not mutated:
            with contextlib.suppress(OSError):
                Path(backup_path).unlink()
            backup_path = None
        raise
    return result

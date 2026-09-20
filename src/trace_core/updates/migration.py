import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.fs import atomic_write_lines, check_contained
from trace_core.core.settings import settings
from trace_core.updates.errors import (
    MigrationCompatibilityError,
    RecoveryError,
    UpdateError,
    UpdateInProgressError,
)


def marker_path() -> Path:
    return Path(settings.storage_root) / "state" / "update-active.json"


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
    return _ambient_tx() == transaction_id


def marker_state() -> tuple[str, dict | None]:
    p = marker_path()
    if not p.exists():
        return "absent", None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "corrupt", None
    if not isinstance(data, dict) or "transaction_id" not in data:
        return "corrupt", None
    return "active", data


def begin_update_migration(transaction_id: str) -> None:
    target = marker_path()
    check_contained(target, settings.storage_root)
    atomic_write_lines(target, [json.dumps({"transaction_id": transaction_id})])


def finish_update_migration(transaction_id: str) -> None:
    state, active = marker_state()
    if state == "active" and active and active.get("transaction_id") != transaction_id:
        raise UpdateInProgressError("another update transaction owns migration")
    marker_path().unlink(missing_ok=True)


def applied_versions(manager: DatabaseSessionManager) -> list[int]:
    from trace_core.core.database.migrations import get_applied_migrations

    return sorted(m["version"] for m in get_applied_migrations(manager.engine))


def current_schema_version(manager: DatabaseSessionManager) -> int:
    applied = applied_versions(manager)
    if applied != list(range(1, max(applied, default=0) + 1)):
        raise MigrationCompatibilityError(f"non-contiguous migrations applied: {applied}")
    return max(applied, default=0)


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
        raise RecoveryError("backup path refused; cannot restore") from None
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise RecoveryError("backup path refused; cannot restore")
    return resolved


def restore_backup(backup_path: str | Path, manager: DatabaseSessionManager) -> None:
    src = _confine_backup_path(backup_path)
    url = manager._url
    if not src.is_file() or src.stat().st_size == 0:
        raise RecoveryError("backup missing or empty; cannot restore")
    if url.startswith("sqlite") and ":memory:" not in url:
        live = Path(url.split("sqlite:///", 1)[1].split("?", 1)[0])
        if manager._engine is not None:
            manager._engine.dispose()
        shutil.copy2(src, live)
        manager._engine = None
        manager._session_factory = None
        return
    if url.startswith("postgresql"):
        import subprocess

        pg_url = re.sub(r"^postgresql\+[^:]+://", "postgresql://", url)
        try:
            with src.open("rb") as handle:
                subprocess.run(
                    ["psql", pg_url, "-f", "-"],
                    stdin=handle,
                    stderr=subprocess.DEVNULL,
                    timeout=600,
                    check=True,
                )
        except (OSError, subprocess.SubprocessError) as e:
            raise RecoveryError(f"database restore failed: {e}") from e
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
    return updater_mod.rollback(base)


def backup_database(manager: DatabaseSessionManager, dest_dir: str | Path) -> Path:
    from sqlalchemy import text

    url = manager._url
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if url.startswith("sqlite") and ":memory:" not in url:
        out = dest / "trace-backup.db"
        check_contained(out, dest)
        if out.exists():
            out.unlink()
        literal = str(out).replace("'", "''")
        with manager.engine.begin() as conn:
            conn.execute(text(f"VACUUM INTO '{literal}'"))
        return out
    if url.startswith("postgresql"):
        out = dest / "trace-backup.sql"
        check_contained(out, dest)
        pg_url = re.sub(r"^postgresql\+[^:]+://", "postgresql://", url)
        try:
            with out.open("wb") as handle:
                subprocess.run(
                    ["pg_dump", pg_url],
                    stdout=handle,
                    stderr=subprocess.DEVNULL,
                    timeout=300,
                    check=True,
                )
        except (OSError, subprocess.SubprocessError) as e:
            raise UpdateError(f"database backup failed: {e}") from e
        if out.stat().st_size == 0:
            raise UpdateError("database backup failed: empty dump")
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
    from trace_core.core.database.migrations import apply_migrations, verify_migration_checksums

    state, active = marker_state()
    if state == "corrupt":
        raise UpdateInProgressError("update marker corrupt; run trace recovery before migrating")
    if state == "active" and active and active.get("transaction_id") != transaction_id:
        raise UpdateInProgressError("another update transaction owns migration")
    begin_update_migration(transaction_id)
    try:
        current = current_schema_version(manager)
        would_advance = schema_target is not None and schema_target > current
        needs_backup = backup_required or (would_advance and backup_waiver is None)
        backup_path = None
        if needs_backup:
            if backup_dir is None:
                raise UpdateError("backup required but no backup directory given")
            backup_path = backup_database(manager, backup_dir)
        verify_compatibility(manager, schema_min, schema_target)
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
        import contextlib

        with contextlib.suppress(UpdateInProgressError):
            finish_update_migration(transaction_id)
        raise
    finish_update_migration(transaction_id)
    return result

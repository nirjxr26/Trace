import json
import time
from dataclasses import dataclass
from pathlib import Path

from trace_core.core.fs import ensure_dir

TRUST_ANCHOR_NAME = "trust anchor"
STATE_FILES_NAME = "state files"


@dataclass
class SelfCheck:
    name: str
    ok: bool
    detail: str
    repaired: bool = False


def _guard(name: str, fn) -> SelfCheck:  # type: ignore[no-untyped-def]
    try:
        return fn()
    except Exception as exc:
        return SelfCheck(name, False, str(exc))


def _reset_corrupt_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return not isinstance(data, dict)
    except (OSError, ValueError, TypeError):
        return True


def _remove(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def state_file_paths() -> tuple[Path, ...]:
    from trace_core.updates.cache import cache_path
    from trace_core.updates.marker import marker_path, storage_state_path

    return (
        cache_path(),
        marker_path(),
        storage_state_path("update-active.json"),
        storage_state_path("update-result.json"),
    )


def artifact_cache_dir() -> Path:
    from trace_core.updates.marker import storage_state_path

    return ensure_dir(storage_state_path("artifacts"))


def check_trust_anchor() -> SelfCheck:
    from trace_core.updates import bootstrap
    from trace_core.updates.signing import import_release_pubkey
    from trace_core.updates.trust import trust_key_path

    def run() -> SelfCheck:
        path = trust_key_path(bootstrap.KEY_ID)
        if path.exists():
            return SelfCheck(TRUST_ANCHOR_NAME, True, "present")
        import_release_pubkey(bootstrap.PUBKEY_HEX)
        return SelfCheck(TRUST_ANCHOR_NAME, True, "provisioned", repaired=True)

    return _guard(TRUST_ANCHOR_NAME, run)


def check_trust_dirs() -> SelfCheck:
    def run() -> SelfCheck:
        from trace_core.updates.trust import trust_root

        ensure_dir(trust_root() / "revoked")
        return SelfCheck("trust dirs", True, "present")

    return _guard("trust dirs", run)


def check_state_json() -> SelfCheck:
    def run() -> SelfCheck:
        repaired = False
        for path in state_file_paths():
            if not path.exists():
                continue
            if _reset_corrupt_json(path):
                if not _remove(path):
                    return SelfCheck(STATE_FILES_NAME, False, f"cannot remove corrupt {path.name}")
                repaired = True
        return SelfCheck(STATE_FILES_NAME, True, "reset" if repaired else "ok", repaired=repaired)

    return _guard(STATE_FILES_NAME, run)


def check_artifact_tmp() -> SelfCheck:
    def run() -> SelfCheck:
        removed = sum(1 for tmp in artifact_cache_dir().glob("*.tmp") if _remove(tmp))
        return SelfCheck("artifact tmp", True, f"removed {removed}" if removed else "clean", repaired=removed > 0)

    return _guard("artifact tmp", run)


def heal_schema_drift() -> bool:
    """Re-apply an already-recorded migration whose verifier now fails.

    Every migration body is written idempotently (IF NOT EXISTS / ensure_column /
    create_all), so replaying one cannot corrupt a correct schema. On a machine where
    nothing was changed, the verifier cost is a handful of column/index lookups and no
    write happens.
    """
    from trace_core.core.database.migrations import MIGRATION_VERIFIERS, MIGRATIONS, apply_migrations
    from trace_core.core.database.session import db_manager

    healed: list[str] = []
    with db_manager.engine.connect() as conn:
        for version, name, action in MIGRATIONS:
            verifier = MIGRATION_VERIFIERS.get(version)
            if verifier is None or not _recorded(conn, version):
                continue
            if verifier(conn):
                continue
            with db_manager.engine.begin() as fix:
                action(fix)
                if verifier is not None and not verifier(fix):
                    raise RuntimeError(f"Migration {name} failed re-verification; rolled back, not repaired.")
            healed.append(name)
    if healed:
        apply_migrations(db_manager.engine)
    return bool(healed)


def _recorded(conn, version: int) -> bool:
    from sqlalchemy import select

    from trace_core.core.database.migrations import schema_migrations

    return (
        conn.execute(select(schema_migrations.c.version).where(schema_migrations.c.version == version)).first()
        is not None
    )


CHECKS = (check_trust_dirs, check_trust_anchor, check_state_json, check_artifact_tmp)

_LAST_HEAL = 0.0
_HEAL_INTERVAL = 300.0


def _maybe_heal() -> None:
    global _LAST_HEAL
    now = time.monotonic()
    if now - _LAST_HEAL < _HEAL_INTERVAL:
        return
    _LAST_HEAL = now
    run_self_heal()
    try:
        heal_schema_drift()
    except Exception:
        pass


def run_self_heal() -> list[SelfCheck]:
    return [check() for check in CHECKS]


def heal_trust_anchor() -> bool:
    return check_trust_anchor().repaired

import json
import time
from pathlib import Path
from typing import Any

from trace_core.core.fs import atomic_write_lines, check_contained
from trace_core.core.settings import settings

TTL_SECONDS = 3600


def cache_path() -> Path:
    return Path(settings.storage_root) / "state" / "update-check.json"


def read_check_cache(max_age: int = TTL_SECONDS) -> dict[str, Any] | None:
    p = cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        checked_at = float(data.get("checked_at", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - checked_at > max_age:
        return None
    return data


def write_check_cache(data: dict[str, Any]) -> Path:
    from trace_core.updates.errors import UpdateError

    target = cache_path()
    check_contained(target, settings.storage_root)
    try:
        payload = json.dumps({**data, "checked_at": time.time()}, indent=2)
    except (TypeError, ValueError) as e:
        raise UpdateError(f"unserializable check cache: {e}") from e
    return atomic_write_lines(target, [payload])


def manifest_identity(target: str) -> dict[str, Any] | None:
    """Content identity for a manifest file. Always rehashes, by design.

    A (mtime, size) fast-path was removed: on coarse filesystems an equal-size
    rewrite inside one mtime tick reused the old sha and served a stale
    manifest for the full TTL — hiding even security releases. Manifests are
    capped at 1 MiB, so hashing costs milliseconds. Correctness over micro-perf.
    """
    if target.startswith(("https://", "http://")):
        return None
    from pathlib import Path as _Path

    from trace_core.core.fs import sha256_file

    try:
        stat = _Path(target).stat()
        return {"sha256": sha256_file(target), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
    except OSError:
        return None


def cache_valid_for(cached: dict[str, Any], target: str, channel: str, identity: dict[str, Any] | None = None) -> bool:
    if cached.get("manifest_path") != str(target) or cached.get("channel") != channel:
        return False
    current = identity if identity is not None else manifest_identity(target)
    if current is None:
        return False
    stored = cached.get("manifest_identity") or {}
    return all(stored.get(k) == v for k, v in current.items())

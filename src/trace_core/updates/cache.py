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
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if time.time() - float(data.get("checked_at", 0)) > max_age:
        return None
    return data


def write_check_cache(data: dict[str, Any]) -> Path:
    target = cache_path()
    check_contained(target, settings.storage_root)
    return atomic_write_lines(target, [json.dumps({**data, "checked_at": time.time()}, indent=2)])


def manifest_identity(target: str) -> dict[str, Any] | None:
    if target.startswith(("https://", "http://")):
        return None
    from pathlib import Path as _Path

    from trace_core.core.fs import sha256_file

    try:
        stat = _Path(target).stat()
        return {"sha256": sha256_file(target), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
    except OSError:
        return None


def cache_valid_for(cached: dict[str, Any], target: str, channel: str) -> bool:
    if cached.get("manifest_path") != str(target) or cached.get("channel") != channel:
        return False
    identity = manifest_identity(target)
    if identity is None:
        return False
    stored = cached.get("manifest_identity") or {}
    return all(stored.get(k) == v for k, v in identity.items())

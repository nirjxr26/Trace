from pathlib import Path

from trace_core.core.fs import check_contained, ensure_dir
from trace_core.core.settings import settings

_TRUST_ROOT_CACHE: Path | None = None


def trust_root() -> Path:
    global _TRUST_ROOT_CACHE
    if _TRUST_ROOT_CACHE is not None and _TRUST_ROOT_CACHE.exists():
        return _TRUST_ROOT_CACHE
    root = ensure_dir(Path(settings.storage_root).parent / "trust" / "releases")
    _TRUST_ROOT_CACHE = root
    return root


def trust_key_path(key_id: str) -> Path:
    from trace_core.updates.errors import UpdateVerificationError

    root = trust_root()
    try:
        return check_contained(root / f"{key_id.removeprefix('ed25519:')}.pub", root)
    except ValueError as e:
        raise UpdateVerificationError(f"refusing trust path for {key_id!r}") from e


def revoked_path(key_id: str) -> Path:
    from trace_core.updates.errors import UpdateVerificationError

    root = trust_root()
    try:
        return check_contained(root / "revoked" / key_id.removeprefix("ed25519:"), root)
    except ValueError as e:
        raise UpdateVerificationError(f"refusing trust path for {key_id!r}") from e

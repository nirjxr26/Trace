import re
from pathlib import Path

from trace_core.core.fs import check_contained, ensure_dir
from trace_core.core.settings import settings

_TRUST_ROOT_CACHE: tuple[str, Path] | None = None

KEY_PREFIX = "ed25519:"
_KEY_SUFFIX_RE = re.compile(r"^[0-9a-f]{16}$")


def _key_suffix(key_id: str) -> str:
    """Validated filename stem for a release key id. Grammar first, containment second.

    Key ids arrive from signed manifests and from operator input, both
    attacker-writable: `ed25519:` collapsed to the revoked directory itself and
    wrote a file where a directory belongs, silently un-revoking every key, and
    `ed25519:../../x` reached check_contained as a traversal.
    """
    from trace_core.updates.errors import UpdateVerificationError

    candidate = key_id.strip()
    if not candidate.startswith(KEY_PREFIX) or not _KEY_SUFFIX_RE.match(candidate[len(KEY_PREFIX) :]):
        raise UpdateVerificationError(f"malformed release key id {key_id!r}")
    return candidate[len(KEY_PREFIX) :]


def trust_root() -> Path:
    global _TRUST_ROOT_CACHE
    storage_root = str(Path(settings.storage_root))
    if _TRUST_ROOT_CACHE is not None and _TRUST_ROOT_CACHE[0] == storage_root and _TRUST_ROOT_CACHE[1].exists():
        return _TRUST_ROOT_CACHE[1]
    root = ensure_dir(Path(settings.storage_root).parent / "trust" / "releases")
    _TRUST_ROOT_CACHE = (storage_root, root)
    return root


def trust_key_path(key_id: str) -> Path:
    from trace_core.updates.errors import UpdateVerificationError

    root = trust_root()
    try:
        return check_contained(root / f"{_key_suffix(key_id)}.pub", root, what="trust key")
    except ValueError as e:
        raise UpdateVerificationError(f"refusing trust path for {key_id!r}") from e


def revoked_path(key_id: str) -> Path:
    from trace_core.updates.errors import UpdateVerificationError

    root = trust_root()
    try:
        return check_contained(root / "revoked" / _key_suffix(key_id), root, what="revocation marker")
    except ValueError as e:
        raise UpdateVerificationError(f"refusing trust path for {key_id!r}") from e

from pathlib import Path

from trace_core.core.fs import ensure_dir
from trace_core.core.settings import settings


def trust_root() -> Path:
    return ensure_dir(Path(settings.storage_root).parent / "trust" / "releases")


def trust_key_path(key_id: str) -> Path:
    return trust_root() / f"{key_id.removeprefix('ed25519:')}.pub"


def revoked_path(key_id: str) -> Path:
    return trust_root() / "revoked" / key_id.removeprefix("ed25519:")

"""Filesystem guardrails: restrictive permissions, containment, atomic writes."""

import os
from collections.abc import Iterable
from pathlib import Path


def ensure_dir(path: str | Path, mode: int = 0o700) -> Path:
    """mkdir -p with explicit owner-only mode. Fails loudly instead of inheriting umask."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    os.chmod(target, mode)
    return target


def check_contained(path: str | Path, root: str | Path, *, what: str = "path") -> Path:
    """Resolve and refuse paths escaping root. Backstop behind input validation."""
    base = Path(root).resolve()
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"Refusing {what} escaping storage root: {path!r}")
    return resolved


def atomic_write_lines(
    path: str | Path,
    lines: Iterable[str],
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    mode: int = 0o600,
) -> Path:
    """Exclusive-create temp + fsync + atomic rename. Never follows symlinks, never partial."""
    target = Path(path)
    ensure_dir(target.parent)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)  # unlink removes a planted symlink itself; never follows it
    with open(tmp, "x", encoding=encoding, newline=newline) as handle:  # noqa: PTH123
        for line in lines:
            handle.write(line)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except Exception:
            pass
    os.chmod(tmp, mode)
    os.replace(tmp, target)
    return target

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
    try:
        base = Path(root).resolve()
        resolved = Path(path).resolve()
    except OSError:
        raise ValueError(f"Refusing {what} escaping storage root")
    if not resolved.is_relative_to(base):
        raise ValueError(f"Refusing {what} escaping storage root")
    return resolved


def sha256_file(path: str | Path) -> str:
    import hashlib

    target = Path(path)
    h = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _acquire(handle: int, blocking: bool) -> bool:
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            return False
        return True
    import fcntl  # type: ignore[import-not-found]

    try:
        fcntl.flock(handle, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
    except OSError:
        return False
    return True


def _release(handle: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl  # type: ignore[import-not-found]

            fcntl.flock(handle, fcntl.LOCK_UN)  # type: ignore[attr-defined]
    except Exception:
        pass


def file_lock(path: str | Path):  # type: ignore[no-untyped-def]
    from contextlib import contextmanager

    @contextmanager
    def _lock():  # type: ignore[no-untyped-def]
        ensure_dir(Path(path).parent)
        handle = open(path, "a+b")  # noqa: PTH123
        try:
            if not _acquire(handle.fileno(), True):
                raise OSError(f"cannot acquire lock {path}")
            yield
        finally:
            _release(handle.fileno())
            handle.close()

    return _lock()


def try_file_lock(path: str | Path):  # type: ignore[no-untyped-def]
    from contextlib import contextmanager

    @contextmanager
    def _lock():  # type: ignore[no-untyped-def]
        ensure_dir(Path(path).parent)
        handle = open(path, "a+b")  # noqa: PTH123
        try:
            yield _acquire(handle.fileno(), False)
        finally:
            _release(handle.fileno())
            handle.close()

    return _lock()

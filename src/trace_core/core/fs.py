"""Filesystem guardrails: restrictive permissions, containment, atomic writes."""

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import IO, Any


def ensure_dir(path: str | Path, mode: int = 0o700) -> Path:
    """mkdir -p with explicit owner-only mode. Fails loudly instead of inheriting umask."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True, mode=mode)
    os.chmod(target, mode)
    return target


def check_contained(path: str | Path, root: str | Path, *, what: str = "path") -> Path:
    """Refuse paths escaping root. Backstop behind input validation.

    The root is NOT resolved before comparison. Resolving both sides made a symlinked
    root vacuously safe — base became the link target, so every candidate beneath it
    compared as contained and the check could never fire. The root is the trust boundary,
    so it is used literally and only the candidate is resolved; a candidate that is itself
    a symlink is resolved to its target and must still land inside the boundary.
    """
    base = Path(root)
    try:
        resolved = Path(path).resolve()
    except OSError:
        raise ValueError(f"Refusing {what} escaping storage root")
    try:
        base_abs = base.absolute()
    except OSError:
        raise ValueError(f"Refusing {what} escaping storage root")
    if not resolved.is_relative_to(base_abs):
        raise ValueError(f"Refusing {what} escaping storage root")
    return resolved


def check_device_contained(path: str | Path, root: str | Path = "/dev", *, what: str = "device") -> Path:
    """Containment for device nodes, where a symlink is legitimate identity [D17].

    `check_contained` deliberately compares the root literally and never resolves it, so
    that a symlinked root cannot make every candidate vacuously contained (H-21). That is
    correct for the storage and trust roots, and it rejects a real device node: Linux
    exposes stable identity at `/dev/disk/by-id/...`, which is a symlink *by design*, and
    the literal root `/dev/disk/by-id` would not contain its own resolved target
    `/dev/nvme0n1`.

    Here the root is a caller-declared device trust boundary that is resolved, so the
    by-id indirection is traversed and containment is judged on the real target. The
    check is therefore stronger than the literal comparison, not weaker: a link inside
    the trusted root is followed and must still land inside it.

    Separate from `check_contained` on purpose so this cannot be reached by a storage or
    trust-root call site. `file_lock` and its O_NOFOLLOW behaviour are untouched; a device
    node is not locked through this path.
    """
    base = Path(root)
    try:
        base_real = base.resolve(strict=True)
    except OSError:
        raise ValueError(f"Refusing {what} with unresolvable device root")
    if not base_real.is_dir():
        raise ValueError(f"Refusing {what} with non-directory device root")
    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise ValueError(f"Refusing {what} that does not exist")
    if resolved == base_real:
        raise ValueError(f"Refusing {what} that is the device root itself")
    if not resolved.is_relative_to(base_real):
        raise ValueError(f"Refusing {what} escaping the trusted device root")
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

    def _write(handle: IO[Any]) -> None:
        for line in lines:
            handle.write(line)

    return _atomic_write(path, mode, _write, encoding, newline)


def atomic_write_bytes(path: str | Path, data: bytes, *, mode: int = 0o600) -> Path:
    """Binary sibling of atomic_write_lines — the same write discipline, one implementation."""

    def _write(handle: IO[Any]) -> None:
        handle.write(data)

    return _atomic_write(path, mode, _write, "utf-8", None, binary=True)


def _atomic_write(
    path: str | Path,
    mode: int,
    write: Callable[[IO[Any]], None],
    encoding: str,
    newline: str | None,
    *,
    binary: bool = False,
) -> Path:
    """The single write discipline: temp in the same dir, fsync, chmod, atomic rename.

    Both public writers funnel through here, so the durability and no-follow-symlink
    guarantees cannot drift apart between the text and binary paths.
    """
    target = Path(path)
    ensure_dir(target.parent)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        handle: IO[Any]
        if binary:
            handle = os.fdopen(fd, "wb")
        else:
            handle = os.fdopen(fd, "w", encoding=encoding, newline=newline)
        with handle:
            write(handle)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


def fsync_dir(path: str | Path) -> None:
    """Flush a directory entry so a rename/create survives a crash.

    fsyncing the file is not enough: the directory entry that names it may still be
    unflushed. Callers that write several files and then a pointer need this between
    steps, or the pointer can land while the files it points at do not.
    """
    try:
        fd = os.open(Path(path), os.O_RDONLY)
    except OSError:
        # Windows cannot open a directory handle at all; POSIX can and must.
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def read_json_record(path: str | Path) -> dict[str, Any] | None:
    """Read a JSON object, or None when absent, unreadable, or not an object.

    Tolerant read half paired with atomic_write_lines. Callers keep their own field
    validation, and any that must tell "absent" from "corrupt" need that distinction,
    so they read the file themselves.
    """
    target = Path(path)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


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


def _open_lock_file(path: Path):
    """Open a lock file without ever following a symlink.

    `open(path, "a+b")` follows symlinks, so a planted link at a lock path created the
    lock outside the intended directory — the opposite of atomic_write_lines' documented
    "never follows symlinks" contract, in the same module. O_NOFOLLOW makes an existing
    symlink a hard error; the read-only probe tells us whether we are creating or opening.
    """
    flags = os.O_RDWR | os.O_CREAT
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        try:
            return os.fdopen(os.open(path, flags | nofollow, 0o600), "r+b", closefd=True), True
        except OSError:
            # On platforms without O_NOFOLLOW (notably Windows) fall through to a
            # read-only probe so an existing file is opened without a create race.
            pass
    try:
        return os.fdopen(os.open(path, os.O_RDONLY | nofollow), "r+b", closefd=True), False
    except FileNotFoundError:
        return os.fdopen(os.open(path, flags | nofollow, 0o600), "r+b", closefd=True), True


def file_lock(path: str | Path, *, blocking: bool = True, raise_on_fail: bool = True):  # type: ignore[no-untyped-def]
    """Exclusive lock on `path`. Yields whether the lock was acquired.

    blocking=False makes acquisition non-blocking; raise_on_fail=False yields the
    failure instead of raising. The two former wrappers differed only in those two
    booleans, so they are one function now.
    """
    from contextlib import contextmanager

    @contextmanager
    def _lock():  # type: ignore[no-untyped-def]
        target = Path(path)
        ensure_dir(target.parent)
        handle, created = _open_lock_file(target)
        try:
            if created:
                try:
                    os.chmod(target, 0o600)
                except OSError:
                    pass
            acquired = _acquire(handle.fileno(), blocking)
            if not acquired and raise_on_fail:
                raise OSError(f"cannot acquire lock {path}")
            yield acquired
        finally:
            if acquired:
                _release(handle.fileno())
            handle.close()

    return _lock()


def try_file_lock(path: str | Path):  # type: ignore[no-untyped-def]
    """Non-blocking lock that yields False rather than raising when contended."""
    return file_lock(path, blocking=False, raise_on_fail=False)

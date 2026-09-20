import threading
from contextlib import contextmanager
from pathlib import Path

from trace_core.core.fs import file_lock
from trace_core.core.settings import settings

_local = threading.local()


def lock_path() -> Path:
    return Path(settings.storage_root) / "update.lock"


@contextmanager
def update_lock():  # type: ignore[no-untyped-def]
    depth = getattr(_local, "depth", 0)
    if depth:
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth = depth
        return
    _local.depth = 1
    try:
        with file_lock(lock_path()):
            yield
    finally:
        _local.depth = 0


@contextmanager
def try_update_lock():  # type: ignore[no-untyped-def]
    from trace_core.core.fs import try_file_lock

    if getattr(_local, "depth", 0):
        yield True
        return
    with try_file_lock(lock_path()) as held:
        yield held

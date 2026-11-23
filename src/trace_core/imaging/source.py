import os
from pathlib import Path
from typing import BinaryIO, Protocol

from trace_core.imaging.domain import (
    ImagingSource,
    ImagingSourceChangedError,
    ImagingSourceReadError,
    ImagingSourceUnavailableError,
)


class SourceReader(Protocol):
    def open(self, offset: int = 0) -> None: ...

    def read(self, size: int) -> bytes: ...

    def seek(self, offset: int) -> None: ...

    def verify_unchanged(self) -> None: ...

    def close(self) -> None: ...


class FileSource:
    def __init__(self, path: Path, expected_stat: os.stat_result) -> None:
        self.path = path
        self._expected = expected_stat
        self._handle: BinaryIO | None = None

    def open(self, offset: int = 0) -> None:
        if self.path.is_symlink():
            raise ImagingSourceUnavailableError("A symlinked fixture source is not accepted for acquisition.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
        except FileNotFoundError as exc:
            raise ImagingSourceUnavailableError("The fixture source is no longer present.") from exc
        except OSError as exc:
            raise ImagingSourceUnavailableError("The fixture source could not be opened read-only.") from exc
        try:
            opened = os.fstat(fd)
            if not self._same_object(opened):
                raise ImagingSourceChangedError("The fixture source changed before the read handle was bound.")
            if offset:
                os.lseek(fd, offset, os.SEEK_SET)
            self._handle = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise

    def read(self, size: int) -> bytes:
        if self._handle is None:
            raise ImagingSourceReadError("The fixture source is not open.")
        try:
            return self._handle.read(size)
        except OSError as exc:
            raise ImagingSourceReadError("The fixture source could not be read.") from exc

    def seek(self, offset: int) -> None:
        if self._handle is None:
            raise ImagingSourceReadError("The fixture source is not open.")
        try:
            self._handle.seek(offset)
        except OSError as exc:
            raise ImagingSourceReadError("The fixture source could not be positioned.") from exc

    def verify_unchanged(self) -> None:
        if self._handle is None:
            raise ImagingSourceChangedError("The fixture source handle is not open.")
        if not self._same_object(os.fstat(self._handle.fileno())):
            raise ImagingSourceChangedError("The fixture source changed while it was being read.")

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        except OSError as exc:
            raise ImagingSourceReadError("The fixture source handle could not be closed.") from exc
        finally:
            self._handle = None

    def _same_object(self, current: os.stat_result) -> bool:
        return (
            current.st_dev == self._expected.st_dev
            and current.st_ino == self._expected.st_ino
            and current.st_size == self._expected.st_size
            and current.st_mtime_ns == self._expected.st_mtime_ns
        )


class BlockDeviceSource:
    def __init__(self, node: str, expected_size: int) -> None:
        self.node = node
        self._expected_size = expected_size
        self._handle: BinaryIO | None = None
        self._identity: tuple[int, int] | None = None

    def open(self, offset: int = 0) -> None:
        fd: int | None = None
        try:
            _, fd = self._open_read_only()
            identity = self._identity_of(fd)
            if offset:
                os.lseek(fd, offset, os.SEEK_SET)
            self._handle = os.fdopen(fd, "rb")
            fd = None
            self._identity = identity
        except OSError as exc:
            if fd is not None:
                os.close(fd)
            raise ImagingSourceUnavailableError("The physical source could not be opened read-only.") from exc

    def read(self, size: int) -> bytes:
        if self._handle is None:
            raise ImagingSourceReadError("The physical source is not open.")
        try:
            return self._handle.read(size)
        except OSError as exc:
            raise ImagingSourceReadError("The physical source could not be read.") from exc

    def seek(self, offset: int) -> None:
        if self._handle is None:
            raise ImagingSourceReadError("The physical source is not open.")
        try:
            self._handle.seek(offset)
        except OSError as exc:
            raise ImagingSourceReadError("The physical source could not be positioned.") from exc

    def verify_unchanged(self) -> None:
        if self._handle is None or self._identity is None:
            raise ImagingSourceChangedError("The physical source handle is not open.")
        current = self._identity_of(self._handle.fileno())
        if current != self._identity:
            raise ImagingSourceChangedError("The physical source changed while it was being read.")

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        except OSError as exc:
            raise ImagingSourceReadError("The physical source handle could not be closed.") from exc
        finally:
            self._handle = None
            self._identity = None

    def _open_read_only(self) -> tuple[int | None, int]:
        if os.name == "nt" and self.node.startswith("\\\\.\\"):
            import msvcrt

            from trace_core.devices.win32 import _close as close_win32
            from trace_core.devices.win32 import _try_open as try_win32

            handle, error = try_win32(self.node)
            if handle is None:
                raise ImagingSourceUnavailableError(
                    f"access denied for {self.node} (Win32 error {error}); re-run elevated"
                )
            try:
                fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
            except OSError:
                close_win32(handle)
                raise
            return handle, fd
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        return None, os.open(self.node, flags)

    def _identity_of(self, fd: int) -> tuple[int, int]:
        stat = os.fstat(fd)
        return stat.st_dev, stat.st_ino


def open_source(source: ImagingSource, expected_stat: os.stat_result | None = None) -> SourceReader:
    if source.kind.value == "OS":
        return BlockDeviceSource(source.node, source.size_bytes)
    if expected_stat is None:
        raise ImagingSourceUnavailableError("The fixture source has no recorded file identity.")
    return FileSource(Path(source.node), expected_stat)

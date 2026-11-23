import hashlib
from collections.abc import Callable
from typing import Any, BinaryIO, Protocol

from trace_core.imaging.domain import ImagingBadRegion, ImagingInterruptedError, ImagingSourceReadError

PIECE_SIZE = 4 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class RawSource(Protocol):
    def read(self, size: int, /) -> bytes: ...

    def seek(self, offset: int, /) -> object: ...


Progress = Callable[[int, int], None]
ProgressWithDigest = Callable[[int, int, str], None]
Cancelled = Callable[[], bool]


def copy_raw_with_regions(
    source: RawSource,
    destination: BinaryIO,
    expected_bytes: int,
    *,
    offset: int = 0,
    progress: Progress | None = None,
    progress_with_digest: ProgressWithDigest | None = None,
    digest: Any | None = None,
    cancelled: Cancelled | None = None,
    on_bad_region: Callable[[ImagingBadRegion], None] | None = None,
) -> tuple[int, str, tuple[ImagingBadRegion, ...]]:
    if expected_bytes < 0:
        raise ValueError("Expected byte count must not be negative.")
    if offset < 0 or offset > expected_bytes:
        raise ValueError("Resume offset must lie inside the expected byte count.")

    digest = digest if digest is not None else hashlib.sha256()
    bad_regions: list[ImagingBadRegion] = []
    copied = 0
    remaining = expected_bytes - offset

    while copied < remaining:
        if cancelled is not None and cancelled():
            raise ImagingInterruptedError("Acquisition cancelled; a resume checkpoint was written.")
        wanted = min(CHUNK_SIZE, remaining - copied)
        try:
            chunk = source.read(wanted)
        except ImagingSourceReadError as exc:
            source.seek(offset + copied + wanted)
            chunk = b"\0" * wanted
            region = ImagingBadRegion(offset=offset + copied, length=wanted, cause=str(exc)[:512])
            bad_regions.append(region)
            if on_bad_region is not None:
                on_bad_region(region)
        if chunk is None:
            raise BlockingIOError("Source read did not complete.")
        if not chunk:
            raise EOFError("Source ended before the expected byte count.")
        if len(chunk) > remaining - copied:
            raise OSError("Source returned more bytes than requested.")
        write_offset = 0
        while write_offset < len(chunk):
            written = destination.write(chunk[write_offset:])
            if written is None or written <= 0 or written > len(chunk) - write_offset:
                raise OSError("Destination did not accept the requested bytes.")
            digest.update(chunk[write_offset : write_offset + written])
            copied += written
            write_offset += written
        if progress_with_digest is not None:
            progress_with_digest(offset + copied, expected_bytes, digest.hexdigest())
        if progress is not None:
            progress(offset + copied, expected_bytes)
    return copied, digest.hexdigest(), tuple(bad_regions)


def copy_raw(source: RawSource, destination: BinaryIO, expected_bytes: int, **kwargs) -> tuple[int, str]:
    copied, digest, _ = copy_raw_with_regions(source, destination, expected_bytes, **kwargs)
    return copied, digest


def hash_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if chunk is None:
            raise BlockingIOError("Image read did not complete.")
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def verify_raw(image: BinaryIO, expected_bytes: int, expected_sha256: str) -> bool:
    if expected_bytes < 0:
        raise ValueError("Expected byte count must not be negative.")

    digest = hashlib.sha256()
    count = 0
    while True:
        chunk = image.read(CHUNK_SIZE)
        if chunk is None:
            raise BlockingIOError("Image read did not complete.")
        if not chunk:
            break
        count += len(chunk)
        if count > expected_bytes:
            return False
        digest.update(chunk)
    return count == expected_bytes and digest.hexdigest() == expected_sha256


def verify_raw_with_pieces(
    image: BinaryIO, expected_bytes: int, expected_sha256: str, piece_size: int = PIECE_SIZE
) -> tuple[bool, tuple[str, ...]]:
    if expected_bytes < 0 or piece_size <= 0:
        raise ValueError("Byte count and piece size must be positive.")

    digest = hashlib.sha256()
    piece = hashlib.sha256()
    pieces: list[str] = []
    count = 0
    piece_count = 0
    while True:
        chunk = image.read(piece_size)
        if chunk is None:
            raise BlockingIOError("Image read did not complete.")
        if not chunk:
            break
        count += len(chunk)
        if count > expected_bytes:
            return False, ()
        digest.update(chunk)
        piece.update(chunk)
        piece_count += len(chunk)
        if piece_count == piece_size:
            pieces.append(piece.hexdigest())
            piece = hashlib.sha256()
            piece_count = 0
    if piece_count:
        pieces.append(piece.hexdigest())
    return count == expected_bytes and digest.hexdigest() == expected_sha256, tuple(pieces)

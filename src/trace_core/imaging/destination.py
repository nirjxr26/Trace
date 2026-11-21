import json
import os
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from trace_core.core.canonical import canonical_json
from trace_core.core.fs import check_contained, ensure_dir, fsync_dir
from trace_core.imaging.domain import (
    ImagingDestinationError,
    ImagingDestinationExistsError,
    ImagingPublishError,
    ImagingReadbackError,
)
from trace_core.imaging.stream import PIECE_SIZE, verify_raw_with_pieces

CHECKPOINT_NAME = "image.partial.checkpoint.json"
_PARTIAL_NAME = "image.partial"


def partial_path(operation_dir: Path) -> Path:
    return operation_dir / _PARTIAL_NAME


def checkpoint_path(operation_dir: Path) -> Path:
    return operation_dir / CHECKPOINT_NAME


def create_partial(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ImagingDestinationExistsError("The partial image already exists; it was not overwritten.") from exc
    except OSError as exc:
        raise ImagingDestinationError("The partial image could not be created exclusively.") from exc
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return os.fdopen(fd, "wb")


def append_partial(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ImagingDestinationError("The partial image could not be opened for resume.") from exc
    return os.fdopen(fd, "ab")


def write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    data = canonical_json(payload) + b"\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def discard_checkpoint(path: Path) -> None:
    path.unlink(missing_ok=True)


def publish_image(partial: Path, image: Path) -> None:
    if image.exists():
        raise ImagingDestinationExistsError("The final image already exists; it was not overwritten.")
    try:
        partial_stat = partial.stat()
    except OSError as exc:
        raise ImagingPublishError("The completed partial image could not be inspected.") from exc
    try:
        os.link(partial, image)
    except FileExistsError as exc:
        raise ImagingDestinationExistsError("The final image already exists; it was not overwritten.") from exc
    except OSError:
        _copy_without_clobber(partial, image)
        partial_stat = image.stat()
    try:
        published = image.stat()
        if (published.st_dev, published.st_ino) != (partial_stat.st_dev, partial_stat.st_ino):
            raise ImagingPublishError("The published image is not the object that was written.")
        fsync_dir(image.parent)
        os.unlink(partial)
        fsync_dir(image.parent)
    except OSError as exc:
        raise ImagingPublishError("The published image could not be confirmed and sealed.") from exc


def _copy_without_clobber(source: Path, target_path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(target_path, flags, 0o600)
    except FileExistsError as exc:
        raise ImagingDestinationExistsError("The destination already exists; it was not overwritten.") from exc
    except OSError as exc:
        raise ImagingDestinationError("The destination could not be created exclusively.") from exc
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as reader:
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    except OSError as exc:
        target_path.unlink(missing_ok=True)
        raise ImagingDestinationError("The destination could not be written.") from exc


def write_manifest(path: Path, data: bytes) -> None:
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        try:
            os.link(tmp, path)
        except FileExistsError as exc:
            raise ImagingDestinationExistsError("The manifest already exists; it was not overwritten.") from exc
        except OSError:
            _copy_without_clobber(tmp, path)
        os.unlink(tmp)
        fsync_dir(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def verify_image(path: Path, expected_bytes: int, expected_sha256: str) -> bool:
    verified, _ = verify_image_with_pieces(path, expected_bytes, expected_sha256)
    return verified


def verify_image_with_pieces(
    path: Path, expected_bytes: int, expected_sha256: str, piece_size: int = PIECE_SIZE
) -> tuple[bool, tuple[str, ...]]:
    try:
        with path.open("rb") as handle:
            return verify_raw_with_pieces(handle, expected_bytes, expected_sha256, piece_size)
    except OSError as exc:
        raise ImagingReadbackError("The image could not be read back for verification.") from exc


def relative_locator(root: Path, path: Path) -> str:
    resolved = check_contained(path, root, what="imaging artifact")
    return resolved.relative_to(Path(root).resolve()).as_posix()

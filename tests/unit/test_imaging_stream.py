import hashlib
import os
from collections.abc import Buffer
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest

from trace_core.imaging.stream import copy_raw, verify_raw

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("size", [0, 1, 1024 * 1024, 1024 * 1024 + 1])
def test_copy_raw_preserves_bytes_and_hash(size: int) -> None:
    data = (b"trace" * ((size + 4) // 5))[:size]
    destination = BytesIO()

    count, digest = copy_raw(BytesIO(data), destination, size)

    assert destination.getvalue() == data
    assert count == size
    assert digest == hashlib.sha256(data).hexdigest()


def test_copy_raw_rejects_premature_eof() -> None:
    with pytest.raises(EOFError, match="Source ended"):
        copy_raw(BytesIO(b"abc"), BytesIO(), 4)


def test_copy_raw_rejects_negative_length() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        copy_raw(BytesIO(), BytesIO(), -1)


def test_copy_raw_handles_partial_writes() -> None:
    class PartialWriter(BytesIO):
        def write(self, data: Buffer, /) -> int:
            return super().write(memoryview(data)[:2])

    destination = PartialWriter()
    count, digest = copy_raw(BytesIO(b"abcdef"), destination, 6)

    assert destination.getvalue() == b"abcdef"
    assert count == 6
    assert digest == hashlib.sha256(b"abcdef").hexdigest()


@pytest.mark.parametrize("result", [0, None, -1, 4])
def test_copy_raw_rejects_invalid_writes(result: int | None) -> None:
    class InvalidWriter(BytesIO):
        def write(self, data: Buffer, /) -> int:
            return cast(int, result)

    source = BytesIO(b"abc")
    destination = InvalidWriter()
    with pytest.raises(OSError, match="did not accept"):
        copy_raw(source, destination, 3)


@pytest.mark.parametrize("size", [0, 1, 1024 * 1024 + 1])
def test_verify_raw_accepts_matching_copy(size: int) -> None:
    data = (b"trace" * ((size + 4) // 5))[:size]
    destination = BytesIO()
    count, digest = copy_raw(BytesIO(data), destination, size)

    assert verify_raw(BytesIO(destination.getvalue()), count, digest)


@pytest.mark.parametrize("data", [b"ab", b"abcd", b"abd"])
def test_verify_raw_rejects_wrong_length_or_digest(data: bytes) -> None:
    assert not verify_raw(BytesIO(data), 3, hashlib.sha256(b"abc").hexdigest())


def test_verify_raw_rejects_negative_length() -> None:
    source = BytesIO()
    digest = hashlib.sha256(b"").hexdigest()
    with pytest.raises(ValueError, match="must not be negative"):
        verify_raw(source, -1, digest)


def test_verify_raw_propagates_read_failure() -> None:
    class BrokenReader(BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            raise OSError("read failed")

    source = BrokenReader()
    digest = hashlib.sha256(b"abc").hexdigest()
    with pytest.raises(OSError, match="read failed"):
        verify_raw(source, 3, digest)


def test_incomplete_source_read_is_not_eof() -> None:
    class IncompleteReader(BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            return cast(bytes, None)

    source = IncompleteReader()
    destination = BytesIO()
    with pytest.raises(BlockingIOError, match="Source read did not complete"):
        copy_raw(source, destination, 1)


def test_incomplete_image_read_never_verifies_empty_image() -> None:
    class IncompleteReader(BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            return cast(bytes, None)

    source = IncompleteReader()
    digest = hashlib.sha256(b"").hexdigest()
    with pytest.raises(BlockingIOError, match="Image read did not complete"):
        verify_raw(source, 0, digest)


def test_file_copy_flush_and_fresh_readback(tmp_path: Path) -> None:
    source = tmp_path / "source"
    image = tmp_path / "image"
    data = b"trace fixture" * 100_000
    source.write_bytes(data)

    with source.open("rb") as reader, image.open("xb") as writer:
        count, digest = copy_raw(reader, writer, len(data))
        writer.flush()
        os.fsync(writer.fileno())

    with image.open("rb") as reader:
        assert verify_raw(reader, count, digest)
    assert image.read_bytes() == data


def test_exclusive_image_creation_preserves_existing_file(tmp_path: Path) -> None:
    image = tmp_path / "image"
    image.write_bytes(b"existing")

    replacement = BytesIO(b"replacement")

    def attempt_copy() -> None:
        with image.open("xb") as writer:
            copy_raw(replacement, writer, 11)

    with pytest.raises(FileExistsError):
        attempt_copy()

    assert image.read_bytes() == b"existing"

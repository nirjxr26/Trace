"""Seeded synthetic disks for the file adapter [D5].

Deterministic by construction: same seed and size produce byte-identical content,
so a golden fingerprint or hash is stable across runs and machines. Importable by
tests and by the Subpart 6 selftest, which is why it is a module and not a script.
"""

import hashlib
from pathlib import Path

from trace_core.core.fs import atomic_write_bytes, ensure_dir

DEFAULT_SEED = b"trace-synthetic-disk"
DEFAULT_SIZE = 4096


def payload(seed: bytes = DEFAULT_SEED, size: int = DEFAULT_SIZE) -> bytes:
    """Deterministic filler of exactly `size` bytes."""
    if size < 0:
        raise ValueError("size must be >= 0")
    out = bytearray()
    block = hashlib.sha256(seed).digest()
    while len(out) < size:
        out.extend(block)
        block = hashlib.sha256(block).digest()
    return bytes(out[:size])


def write_disk(path: str | Path, seed: bytes = DEFAULT_SEED, size: int = DEFAULT_SIZE) -> Path:
    """Materialise a synthetic disk and return its path, creating missing ancestors."""
    target = Path(path)
    ensure_dir(target.parent)
    atomic_write_bytes(target, payload(seed, size))
    return target


SYNTHETIC_SERIAL_WIDTH = 32
LEGACY_SYNTHETIC_SERIAL_WIDTH = 16


def synthetic_serial(content_hash: str) -> str:
    """Serial derived from content, never from hardware [D13]."""
    return f"SYNTH-{content_hash[:SYNTHETIC_SERIAL_WIDTH]}"


def synthetic_serial_variants(serial: str) -> tuple[str, ...]:
    """Stored forms of a synthetic serial: the current width plus its legacy truncation."""
    if not is_synthetic_serial(serial):
        return (serial,)
    hexdigest = serial.removeprefix("SYNTH-")
    if len(hexdigest) != SYNTHETIC_SERIAL_WIDTH:
        return (serial,)
    return (serial, f"SYNTH-{hexdigest[:LEGACY_SYNTHETIC_SERIAL_WIDTH]}")


def absent_serial(node: str, *, size_bytes: int | None = None, model: str | None = None) -> str:
    """Serial for a device that vanished: deterministic, never content-derived [D13]."""
    observed = f"absent:{node}:{size_bytes if size_bytes is not None else '?'}:{model or '?'}"
    return synthetic_serial(hashlib.sha256(observed.encode()).hexdigest())


def is_synthetic_serial(serial: str) -> bool:
    return serial.startswith("SYNTH-")

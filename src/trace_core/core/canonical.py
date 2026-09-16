"""Canonical JSON serialization for forensic hashing and audit payloads."""

import json
import math
from datetime import UTC, datetime
from typing import Any


def coerce_utc(dt: datetime | None) -> datetime | None:
    """Coerce naive datetime to UTC, pass through aware as UTC. Single source."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def canonical_ts(dt: datetime) -> str:
    """UTC Zulu string single source for hashing, export, and anchors."""
    coerced = coerce_utc(dt)
    assert coerced is not None
    return coerced.isoformat().replace("+00:00", "Z")


def parse_trailing_seq(value: str) -> int | None:
    """Trailing integer after a dash/number suffix, else None. Shared by anchors + sequences."""
    text = value.strip()
    if not text:
        return None
    tail = text.rsplit("-", 1)[-1] if "-" in text else text
    return int(tail) if tail.isdigit() else None


def _normalize_value(value: Any) -> Any:
    """Recursively normalize values for deterministic serialization."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("Non-finite float not allowed in canonical JSON")
    if isinstance(value, datetime):
        return canonical_ts(value)
    if isinstance(value, dict):
        return {k: _normalize_value(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    return value


def canonical_json(obj: dict[str, Any]) -> bytes:
    """Serialize dict to canonical JSON bytes for hashing."""
    normalized = _normalize_value(obj)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def canonical_json_str(obj: dict[str, Any]) -> str:
    """Canonical JSON text single source for export/audit payloads."""
    return canonical_json(obj).decode("utf-8")

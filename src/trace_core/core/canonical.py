"""Canonical JSON serialization for forensic hashing and audit payloads."""

import json
from datetime import UTC, datetime
from typing import Any


def _normalize_value(value: Any) -> Any:
    """Recursively normalize values for deterministic serialization."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: _normalize_value(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    return value


def canonical_json(obj: dict[str, Any]) -> bytes:
    """Serialize dict to canonical JSON bytes for hashing."""
    normalized = _normalize_value(obj)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

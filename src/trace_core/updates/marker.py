import json
from pathlib import Path
from typing import Any

from trace_core.core.fs import atomic_write_lines, check_contained
from trace_core.core.settings import settings
from trace_core.updates.errors import RecoveryError

MARKER_SCHEMA = 2
SCHEMA_REQUIRED_KEYS: dict[int, tuple[str, ...]] = {
    MARKER_SCHEMA: ("marker_schema", "transaction_id", "state"),
}
REQUIRED_KEYS = SCHEMA_REQUIRED_KEYS[MARKER_SCHEMA]


def marker_path() -> Path:
    return Path(settings.storage_root) / "update-result.json"


def write_marker(data: dict[str, Any], path: str | Path | None = None) -> Path:
    target = Path(path) if path else marker_path()
    check_contained(target, settings.storage_root)
    missing = [k for k in ("transaction_id", "state") if k not in data]
    if missing:
        raise ValueError(f"marker missing fields: {missing}")
    record = {"marker_schema": MARKER_SCHEMA, **data}
    return atomic_write_lines(target, [json.dumps(record, indent=2)])


def read_marker(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else marker_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RecoveryError("no update marker found; manual inspection required") from None
    except (OSError, ValueError) as e:
        raise RecoveryError("corrupt update marker; manual inspection required") from e
    if not isinstance(data, dict):
        raise RecoveryError("corrupt update marker; manual inspection required")
    schema = data.get("marker_schema")
    required = SCHEMA_REQUIRED_KEYS.get(schema) if isinstance(schema, int) else None
    if required is None:
        raise RecoveryError(f"unsupported marker schema {data.get('marker_schema')!r}")
    missing = [k for k in required if k not in data]
    if missing:
        raise RecoveryError(f"update marker missing fields: {missing}")
    return data

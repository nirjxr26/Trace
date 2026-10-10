import json
from pathlib import Path
from typing import Any

from trace_core.core.fs import JsonFileVerdict, atomic_write_lines, check_contained, classify_json_file
from trace_core.core.settings import settings
from trace_core.updates.errors import RecoveryError

MARKER_SCHEMA = 2
SCHEMA_REQUIRED_KEYS: dict[int, tuple[str, ...]] = {
    MARKER_SCHEMA: ("marker_schema", "transaction_id", "state"),
}
REQUIRED_KEYS = SCHEMA_REQUIRED_KEYS[MARKER_SCHEMA]
# The writer stamps marker_schema itself, so only the caller's fields are checked.
# Derived rather than re-spelled: the two copies had drifted, and the writer's copy
# silently disagreed with the reader's contract.
CALLER_REQUIRED_KEYS = tuple(k for k in REQUIRED_KEYS if k != "marker_schema")


def storage_state_path(name: str) -> Path:
    """Path under <storage>/state/ for update bookkeeping. Single source for the layout
    documented in trace_updater.updater.install_root (update-active.json, update.lock, artifacts/)."""
    return Path(settings.storage_root) / "state" / name


def marker_path() -> Path:
    return Path(settings.storage_root) / "update-result.json"


def write_marker(data: dict[str, Any], path: str | Path | None = None) -> Path:
    from trace_core.updates.domain import UpdateState
    from trace_core.updates.errors import UpdateError

    target = Path(path) if path else marker_path()
    check_contained(target, settings.storage_root)
    missing = [k for k in CALLER_REQUIRED_KEYS if k not in data]
    if missing:
        raise UpdateError(f"marker missing fields: {missing}")
    state = data.get("state")
    if not isinstance(state, str) or state not in {member.value for member in UpdateState}:
        raise UpdateError(f"marker state {state!r} is not an UpdateState")
    if not str(data.get("transaction_id") or "").strip():
        raise UpdateError("marker transaction_id must be non-empty")
    record = {**data, "marker_schema": MARKER_SCHEMA}
    return atomic_write_lines(target, [json.dumps(record, indent=2)])


def read_marker(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else marker_path()
    if not target.exists():
        raise RecoveryError("no update marker found; manual inspection required") from None
    verdict, data = classify_json_file(target)
    if verdict is JsonFileVerdict.UNREADABLE:
        raise RecoveryError("could not read the update marker; left in place, retry or inspect") from None
    if verdict is not JsonFileVerdict.OK or data is None:
        raise RecoveryError("corrupt update marker; manual inspection required") from None
    schema = data.get("marker_schema")
    required = SCHEMA_REQUIRED_KEYS.get(schema) if isinstance(schema, int) else None
    if required is None:
        raise RecoveryError(f"unsupported marker schema {data.get('marker_schema')!r}")
    missing = [k for k in required if k not in data]
    if missing:
        raise RecoveryError(f"update marker missing fields: {missing}")
    return data

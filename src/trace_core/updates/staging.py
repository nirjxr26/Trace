import json
from pathlib import Path
from typing import Any

from trace_core.core.fs import atomic_write_lines, read_json_record, sha256_file

REQUIRED_KEYS = (
    "release_id",
    "version",
    "filename",
    "expected_sha256",
    "actual_sha256",
    "signing_key_id",
    "verification",
)

STAGED_RECORD_FILENAME = "staged.json"
STAGED_SCHEMA = 1


def staged_record_path(staging_dir: str | Path) -> Path:
    return Path(staging_dir) / STAGED_RECORD_FILENAME


def write_staged_record(staging_dir: str | Path, record: dict[str, Any]) -> Path:
    from trace_core.updates.errors import UpdateError

    missing = [k for k in REQUIRED_KEYS if k not in record]
    if missing:
        raise UpdateError(f"incomplete staged record: {missing}")
    target = staged_record_path(staging_dir)
    record = {**record, "staged_schema": STAGED_SCHEMA}
    return atomic_write_lines(target, [json.dumps(record, indent=2)])


def read_staged_record(staging_dir: str | Path) -> dict[str, Any] | None:
    data = read_json_record(staged_record_path(staging_dir))
    if data is None or any(k not in data for k in REQUIRED_KEYS):
        return None
    if data.get("staged_schema") != STAGED_SCHEMA:
        return None
    return data


def is_verified_stage(staging_dir: str | Path, artifact_path: str | Path) -> bool:
    record = read_staged_record(staging_dir)
    if not record or record.get("verification") != "passed":
        return False
    if record.get("actual_sha256") != record.get("expected_sha256"):
        return False
    try:
        return sha256_file(artifact_path) == record["actual_sha256"]
    except OSError:
        return False

import hashlib
import json
from pathlib import Path

import pytest

from trace_core.updates.errors import RecoveryError
from trace_core.updates.marker import MARKER_SCHEMA, read_marker, write_marker

pytestmark = pytest.mark.unit


def test_write_requires_identity(temp_storage_root: Path):
    from trace_core.updates.errors import UpdateError

    path = temp_storage_root / "m.json"
    with pytest.raises(UpdateError):
        write_marker({"state": "IDLE"}, path)


def test_unknown_schema_fails_closed(temp_storage_root: Path):
    path = temp_storage_root / "m.json"
    path.write_text(json.dumps({"marker_schema": 999, "transaction_id": "t", "state": "IDLE"}), encoding="utf-8")
    with pytest.raises(RecoveryError):
        read_marker(path)


def test_missing_fields_fail_closed(temp_storage_root: Path):
    path = temp_storage_root / "m.json"
    path.write_text(json.dumps({"marker_schema": MARKER_SCHEMA, "transaction_id": "t"}), encoding="utf-8")
    with pytest.raises(RecoveryError):
        read_marker(path)


def test_roundtrip(temp_storage_root: Path):
    path = temp_storage_root / "m.json"
    write_marker({"transaction_id": "t1", "state": "STAGED", "release_id": "r"}, path)
    data = read_marker(path)
    assert data["marker_schema"] == MARKER_SCHEMA
    assert data["state"] == "STAGED"


def test_caller_cannot_override_schema(temp_storage_root: Path):
    """A caller-supplied marker_schema must not displace the enforced version."""
    path = temp_storage_root / "m.json"
    write_marker({"transaction_id": "t1", "state": "IDLE", "marker_schema": 999}, path)
    assert json.loads(path.read_text(encoding="utf-8"))["marker_schema"] == MARKER_SCHEMA
    assert read_marker(path)["marker_schema"] == MARKER_SCHEMA


def test_partial_binding_mismatch_discards(temp_storage_root: Path):
    import json as _json

    from trace_updater import updater as updater_mod

    staging = temp_storage_root / "staging"
    staging.mkdir()
    src = temp_storage_root / "a.bin"
    src.write_bytes(b"0123456789")
    digest = hashlib.sha256(b"0123456789").hexdigest()
    (staging / "a.bin.partial").write_bytes(b"XXXXX")
    (staging / "a.bin.partial.json").write_text(
        _json.dumps({"transaction_id": "tx-1", "release_id": "r1", "version": "1.0.0"}), encoding="utf-8"
    )
    second = updater_mod.stage_artifact(
        src,
        staging,
        expected_sha256=digest,
        binding={"transaction_id": "tx-2", "release_id": "r1", "version": "1.0.0"},
    )
    assert second.exists()
    assert second.read_bytes() == b"0123456789"


def test_partial_matching_binding_resumes(temp_storage_root: Path):
    import json as _json

    from trace_updater import updater as updater_mod

    staging = temp_storage_root / "staging"
    staging.mkdir()
    src = temp_storage_root / "a.bin"
    src.write_bytes(b"0123456789")
    digest = hashlib.sha256(b"0123456789").hexdigest()
    binding = {"transaction_id": "tx-1", "release_id": "r1", "version": "1.0.0"}
    (staging / "a.bin.partial").write_bytes(b"01234")
    (staging / "a.bin.partial.json").write_text(
        _json.dumps({**binding, "filename": "a.bin", "expected_sha256": digest, "expected_size": 10}),
        encoding="utf-8",
    )
    second = updater_mod.stage_artifact(src, staging, expected_sha256=digest, binding=binding)
    assert second.read_bytes() == b"0123456789"

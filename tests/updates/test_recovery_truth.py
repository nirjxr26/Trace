"""`trace recovery` must not invent facts, and must not be repeatable into damage.

Three defects, one file, because they all live in the same command:
  - it deleted a marker it had only proven was unlocked, calling it "stale"
  - it printed a SHA-256 of the corrupt file as though it were a transaction id
  - it never recorded a successful rollback, so a second run rolled back again — onto the
    release that had just failed, because _advance_previous had retargeted previous-version
"""

import json
from pathlib import Path

import pytest


def test_shared_classifier_reports_ok_with_data_and_corrupt_without(tmp_path) -> None:
    from trace_core.core.fs import JsonFileVerdict, classify_json_file

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"transaction_id": "tx-1"}), encoding="utf-8")
    assert classify_json_file(good) == (JsonFileVerdict.OK, {"transaction_id": "tx-1"})

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    verdict, data = classify_json_file(bad)
    assert verdict is JsonFileVerdict.CORRUPT
    assert data is None

    wrong_type = tmp_path / "list.json"
    wrong_type.write_text("[1, 2, 3]", encoding="utf-8")
    assert classify_json_file(wrong_type)[0] is JsonFileVerdict.CORRUPT


def test_shared_classifier_reports_unreadable_without_deleting(tmp_path, monkeypatch) -> None:
    from trace_core.core.fs import JsonFileVerdict, classify_json_file

    locked = tmp_path / "locked.json"
    locked.write_text(json.dumps({"transaction_id": "tx-1"}), encoding="utf-8")

    def _refuse_read(*_a, **_k):
        raise PermissionError(32, "file in use by another process")

    monkeypatch.setattr(type(locked), "read_text", _refuse_read)
    try:
        assert classify_json_file(locked) == (JsonFileVerdict.UNREADABLE, None)
    finally:
        monkeypatch.setattr(type(locked), "read_text", Path.read_text)
    assert locked.exists()


def test_marker_state_and_selfheal_agree_a_locked_file_is_unreadable(tmp_path, monkeypatch) -> None:
    from trace_core.updates import migration, selfheal

    locked = tmp_path / "update-active.json"
    locked.write_text(json.dumps({"transaction_id": "tx-1"}), encoding="utf-8")
    monkeypatch.setattr(migration, "migration_marker_path", lambda: locked)
    monkeypatch.setattr(selfheal, "state_file_paths", lambda: (locked,))

    def _refuse_read(*_a, **_k):
        raise PermissionError(32, "file in use by another process")

    monkeypatch.setattr(type(locked), "read_text", _refuse_read)
    try:
        assert migration.marker_state() == ("unreadable", None)
        result = selfheal.check_state_json()
    finally:
        monkeypatch.setattr(type(locked), "read_text", Path.read_text)
    assert result.ok is False
    assert result.repaired is False
    assert locked.exists()


def test_sqlite_sidecars_is_the_single_source_for_both_names(tmp_path) -> None:
    from trace_core.core.fs import sqlite_sidecars

    live = tmp_path / "trace.db"
    assert sqlite_sidecars(live) == (Path(f"{live}-wal"), Path(f"{live}-shm"))


def _write_active(marker_file, state="FAILED", backup_path=None):
    marker_file.write_text(
        json.dumps(
            {
                "transaction_id": "tx-1",
                "state": state,
                "marker_schema": 1,
                "backup_path": backup_path,
                "from_version": "0.2.3",
                "to_version": "0.2.4",
            }
        ),
        encoding="utf-8",
    )


def test_an_unreadable_marker_is_never_deleted(tmp_path, monkeypatch) -> None:
    """Holding the lock proves no updater is running. It does not prove the marker is
    stale, and the marker is the only record that an update owned migrations."""
    from trace_core.core.cli import recovery
    from trace_core.updates import migration
    from trace_core.updates.errors import RecoveryError

    p = migration.migration_marker_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"transaction_id": "tx-1"}), encoding="utf-8")

    def _locked():
        return ("unreadable", None)

    monkeypatch.setattr(migration, "marker_state", _locked)
    monkeypatch.setattr(recovery, "marker_state", _locked, raising=False)

    with pytest.raises(RecoveryError, match="left in place"):
        recovery._triage_update_marker()
    assert p.exists(), "the only record of an interrupted update must survive"


def test_a_corrupt_marker_is_not_reported_with_a_fabricated_transaction_id(tmp_path, monkeypatch, capsys) -> None:
    """`corrupt-<sha256 of the file's own bytes>` was printed as `transaction ...`. It is
    not a transaction id and matches nothing."""
    from trace_core.core.cli import recovery
    from trace_core.updates import migration

    p = migration.migration_marker_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not-json", encoding="utf-8")

    monkeypatch.setattr(migration, "marker_state", lambda: ("corrupt", None))
    monkeypatch.setattr(recovery, "marker_state", lambda: ("corrupt", None), raising=False)

    recovery._triage_update_marker()
    out = capsys.readouterr().out
    assert "corrupt-" not in out, out
    assert "transaction tx-" not in out.lower(), out
    assert "corrupt-unknown" not in out, out
    assert "could not be read" in out, out
    assert not p.exists(), "a genuinely corrupt marker is still cleared"


def test_marker_state_separates_unreadable_from_corrupt(monkeypatch) -> None:
    """The classifier four callers share. Returning "corrupt" for an OSError is what let
    selfheal-style code delete a locked file, and told operators to inspect a file that
    was perfectly intact."""
    from trace_core.updates import migration

    marker = migration.migration_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)

    def _refuse_read(*_a, **_k):
        raise PermissionError(32, "file in use by another process")

    marker.write_text(json.dumps({"transaction_id": "tx-1"}), encoding="utf-8")
    original = type(marker).read_text
    monkeypatch.setattr(type(marker), "read_text", _refuse_read)
    try:
        state, _data = migration.marker_state()
    finally:
        monkeypatch.setattr(type(marker), "read_text", original)
    assert state == "unreadable", state

    marker.write_text("{not json", encoding="utf-8")
    assert migration.marker_state()[0] == "corrupt", "genuinely bad JSON is still corrupt"

    marker.write_text(json.dumps({"transaction_id": "tx-1"}), encoding="utf-8")
    assert migration.marker_state()[0] == "active"

    marker.unlink(missing_ok=True)
    assert migration.marker_state()[0] == "absent"


def test_read_marker_names_an_unreadable_file_as_unreadable(monkeypatch) -> None:
    """marker.py raised RecoveryError("corrupt update marker") for a locked file, telling
    the operator their marker was damaged when it was only inaccessible."""
    from trace_core.updates import marker as marker_mod
    from trace_core.updates.errors import RecoveryError

    p = marker_mod.marker_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"state": "FAILED", "transaction_id": "tx-1"}), encoding="utf-8")

    def _refuse_read(*_a, **_k):
        raise PermissionError(32, "file in use by another process")

    original = type(p).read_text
    monkeypatch.setattr(type(p), "read_text", _refuse_read)
    try:
        with pytest.raises(RecoveryError) as caught:
            marker_mod.read_marker(p)
    finally:
        monkeypatch.setattr(type(p), "read_text", original)
    message = str(caught.value).lower()
    assert "could not read" in message, message
    assert "corrupt" not in message, message
    assert p.exists(), "the file must survive"


def test_a_successful_rollback_records_its_outcome(tmp_path, monkeypatch, capsys) -> None:
    """Without this the marker stayed RECOVERY_REQUIRED, which is in
    _ROLLBACK_WORTHY_STATES, so a second `trace recovery` rolled back again."""
    from trace_core.core.cli import recovery
    from trace_core.updates import marker as marker_mod

    written: list[dict] = []
    monkeypatch.setattr(marker_mod, "write_marker", lambda data, *a, **k: written.append(data))

    recovery._mark_rolled_back({"transaction_id": "tx-1", "state": "RECOVERY_REQUIRED"})
    assert written, "the outcome must be recorded"
    assert written[0]["state"] == "ROLLED_BACK", written
    assert written[0]["rollback"] is True, written


def test_recovery_required_can_be_discharged() -> None:
    """It had one outgoing edge and no caller ever took it, so a user who reached it was
    stranded."""
    from trace_core.updates.domain import UpdateState, can_transition

    assert can_transition(UpdateState.RECOVERY_REQUIRED, UpdateState.ROLLED_BACK)
    assert can_transition(UpdateState.RECOVERY_REQUIRED, UpdateState.IDLE)


def test_rolled_back_is_terminal() -> None:
    """previous-version now names the release that just failed. A second rollback would
    re-activate it and report success."""
    from trace_core.updates.domain import UpdateState, can_transition

    assert can_transition(UpdateState.ROLLED_BACK, UpdateState.IDLE) is False
    assert can_transition(UpdateState.ROLLED_BACK, UpdateState.ROLLED_BACK) is False

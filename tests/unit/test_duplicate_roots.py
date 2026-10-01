"""Guards for three audit findings whose root cause was one duplicated decision each.

R-65 / H-59  a SQLAlchemy URL was string-split in two places. `sqlite://` produced a
             path containing ':' — illegal on Windows, so the migration lock raised
             before any migration ran — and `restore_backup` raised a bare IndexError
             from a recovery path.
H-79 / §4.2  two migrations sharing a version is silent and unrecoverable: apply sorts
             by version, so the later verifier replaces the earlier and only one runs.
§4.5         write_marker re-spelled the required-key tuple and its copy had drifted
             from the reader's contract.
"""

import json
from pathlib import Path

import pytest

from trace_core.core.database import migrations as mig
from trace_core.core.database.session import sqlite_file_path
from trace_core.core.settings import settings
from trace_core.updates.errors import UpdateError
from trace_core.updates.marker import (
    CALLER_REQUIRED_KEYS,
    MARKER_SCHEMA,
    REQUIRED_KEYS,
    SCHEMA_REQUIRED_KEYS,
    write_marker,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///trace.db", "trace.db"),
        ("sqlite+pysqlite:///trace.db", "trace.db"),
        ("sqlite:///trace.db?mode=ro", "trace.db"),
        ("sqlite:///:memory:", None),
        ("sqlite://", None),
        ("sqlite:", None),
        ("postgresql://u:p@h/db", None),
        ("", None),
    ],
)
def test_sqlite_file_path_parses_rather_than_splits(url: str, expected: str | None):
    assert sqlite_file_path(url) == (None if expected is None else Path(expected))


def test_driver_suffix_does_not_leak_into_the_path():
    """The whole point: `+pysqlite` is a scheme suffix, not part of the filename."""
    assert sqlite_file_path("sqlite+pysqlite:///trace.db") == sqlite_file_path("sqlite:///trace.db")


def test_never_returns_a_path_containing_windows_illegal_characters():
    for url in ("sqlite://", "sqlite:", "sqlite:///a.db", "sqlite+pysqlite:///a.db"):
        path = sqlite_file_path(url)
        if path is not None:
            assert not [c for c in str(path) if c in ':*?"<>|'], f"{url} produced {path}"


def test_lock_path_is_derived_from_the_same_helper():
    assert mig._sqlite_lock_path("sqlite+pysqlite:///trace.db") == mig._sqlite_lock_path("sqlite:///trace.db")
    lock_path = mig._sqlite_lock_path("sqlite:///x.db")
    assert lock_path is not None
    assert lock_path.endswith("x.db.migratelock")
    assert mig._sqlite_lock_path("sqlite:///:memory:") is None
    assert mig._sqlite_lock_path("postgresql://u:p@h/db") is None


def test_duplicate_migration_version_is_refused_at_registration():
    existing_version, existing_name = mig.MIGRATIONS[2][0], mig.MIGRATIONS[2][1]
    with pytest.raises(RuntimeError, match="duplicate migration"):

        @mig.register_migration(existing_version, "a_completely_new_name", operations=("probe",))
        def _dup_version(bind):  # type: ignore[no-untyped-def]
            pass

    with pytest.raises(RuntimeError, match="duplicate migration"):

        @mig.register_migration(999, existing_name, operations=("probe",))
        def _dup_name(bind):  # type: ignore[no-untyped-def]
            pass


def test_a_fresh_version_and_name_are_accepted_and_leave_no_residue():
    """A new migration must extend the registry, not sit at an arbitrary number.

    H-64: an arbitrary version was accepted even though applying migrations sorts by
    version, so inserting one above the head silently forked history. The guard now
    requires contiguous 1..N, so "adding a migration" means head+1 and nothing else.
    """
    before = list(mig.MIGRATIONS)
    next_version = max(v for v, _, _ in before) + 1
    name = f"{next_version:03d}_probe_unique"
    try:

        @mig.register_migration(next_version, name, operations=("probe",))
        def _probe(bind):  # type: ignore[no-untyped-def]
            pass

        assert (next_version, name) in [(v, n) for v, n, _ in mig.MIGRATIONS]
    finally:
        mig.MIGRATIONS[:] = before
        mig.MIGRATION_OPERATIONS.pop(next_version, None)
        mig.MIGRATION_VERIFIERS.pop(next_version, None)


def test_a_non_contiguous_version_is_refused():
    """H-64: a gap forks history silently — an existing DB never applies it, a fresh one does."""
    before = list(mig.MIGRATIONS)
    head = max(v for v, _, _ in before)
    try:
        with pytest.raises(RuntimeError, match="contiguous"):
            mig.register_migration(head + 5, f"{head + 5:03d}_gapped", operations=("probe",))(lambda bind: None)
    finally:
        mig.MIGRATIONS[:] = before
        mig.MIGRATION_OPERATIONS.pop(head + 5, None)
        mig.MIGRATION_VERIFIERS.pop(head + 5, None)


def test_production_registry_is_contiguous():
    versions = [v for v, _, _ in mig.MIGRATIONS]
    assert versions == list(range(1, len(versions) + 1)), "registry must be 1..N with no gaps"


def test_every_production_migration_is_unique():
    versions = [v for v, _, _ in mig.MIGRATIONS]
    names = [n for _, n, _ in mig.MIGRATIONS]
    assert len(versions) == len(set(versions)), "duplicate migration version registered"
    assert len(names) == len(set(names)), "duplicate migration name registered"


def test_marker_writer_derives_its_required_keys_from_the_reader_contract():
    """The two copies had drifted: the writer's silently omitted marker_schema."""
    assert set(CALLER_REQUIRED_KEYS) == {"transaction_id", "state"}
    assert set(REQUIRED_KEYS) == set(CALLER_REQUIRED_KEYS) | {"marker_schema"}
    assert SCHEMA_REQUIRED_KEYS[MARKER_SCHEMA] == REQUIRED_KEYS


def test_marker_writer_rejects_each_caller_required_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    for missing in CALLER_REQUIRED_KEYS:
        payload = {"transaction_id": "tx-1", "state": "AVAILABLE"}
        payload.pop(missing)
        with pytest.raises(UpdateError, match="missing fields"):
            write_marker(payload, tmp_path / "storage" / "update-result.json")


def test_marker_writer_still_stamps_the_schema_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    target = tmp_path / "storage" / "update-result.json"
    write_marker({"transaction_id": "tx-1", "state": "AVAILABLE"}, target)
    assert json.loads(target.read_text(encoding="utf-8"))["marker_schema"] == MARKER_SCHEMA

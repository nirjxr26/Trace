"""H-57: migration integrity is independent of Python formatting.

The retired scheme hashed `inspect.getsource(action)`, which includes the decorator
line — so a comment, a reformat, or any edit to the @register_migration call
hard-failed every deployed install with no bypass flag. Identity is now the declared
schema operations, canonicalised and hashed. A genuine change to what a migration
does must still be detected; formatting must not matter, and the source-text path
must not be reintroduced.
"""

import pytest
from sqlalchemy import text

from trace_core.core.database.migrations import (
    CHECKSUM_SCHEME,
    MIGRATION_OPERATIONS,
    MIGRATIONS,
    _migration_checksum,
    get_applied_migrations,
    verify_migration_checksums,
)


def test_every_migration_declares_its_operations():
    assert MIGRATIONS, "no migrations registered"
    for version, name, _action in MIGRATIONS:
        declared = MIGRATION_OPERATIONS.get(version)
        assert declared, f"migration {version} {name} declares no operations"
        assert all(isinstance(op, str) and op for op in declared), f"migration {version} has a non-string operation"


def test_source_text_cannot_reach_the_identity():
    """The removed possibility. Reintroducing getsource here re-bricks every install."""
    import inspect

    from trace_core.core.database import migrations as mig

    fingerprint = inspect.getsource(mig._migration_checksum)
    assert "getsource" not in fingerprint
    assert "getsource" not in inspect.getsource(mig.verify_migration_checksums)
    module_source = inspect.getsource(mig)
    assert "getsource" not in module_source, "migrations.py still hashes Python source somewhere"


def test_identity_is_a_pure_function_of_version_name_and_declared_operations(monkeypatch):
    """Reformatting cannot change it because no formatting is an input at all."""
    baseline = _migration_checksum(3, "003_create_case_sequences_table")
    monkeypatch.setitem(MIGRATION_OPERATIONS, 3, ("create_all:case_sequences",))
    assert _migration_checksum(3, "003_create_case_sequences_table") == baseline
    monkeypatch.setitem(MIGRATION_OPERATIONS, 3, ("create_all:case_sequences", "DROP TABLE case_sequences"))
    assert _migration_checksum(3, "003_create_case_sequences_table") != baseline


def test_identity_separates_versions_and_names(monkeypatch):
    """Two migrations sharing operations must not share an identity."""
    monkeypatch.setitem(MIGRATION_OPERATIONS, 900, ("create_all:x",))
    monkeypatch.setitem(MIGRATION_OPERATIONS, 901, ("create_all:x",))
    assert _migration_checksum(900, "same") != _migration_checksum(901, "same")
    assert _migration_checksum(900, "same") != _migration_checksum(900, "other")


def test_operations_order_is_part_of_the_identity(monkeypatch):
    """Reordering declared operations is a different migration, not a cosmetic edit."""
    monkeypatch.setitem(MIGRATION_OPERATIONS, 902, ("a", "b"))
    forward = _migration_checksum(902, "x")
    monkeypatch.setitem(MIGRATION_OPERATIONS, 902, ("b", "a"))
    assert _migration_checksum(902, "x") != forward


def test_scheme_marker_is_written_for_freshly_applied_migrations(session_manager):
    verify_migration_checksums(session_manager.engine)
    rows = {m["version"]: m for m in get_applied_migrations(session_manager.engine)}
    assert rows, "session_manager fixture applied no migrations"
    assert all(row["checksum_scheme"] == CHECKSUM_SCHEME for row in rows.values())


def test_a_tampered_canonical_checksum_fails_closed(session_manager):
    verify_migration_checksums(session_manager.engine)
    with session_manager.engine.begin() as conn:
        conn.execute(text("UPDATE schema_migrations SET checksum='0' WHERE version=10"))
    with pytest.raises(RuntimeError, match="drift"):
        verify_migration_checksums(session_manager.engine)


def test_a_row_with_a_foreign_scheme_is_treated_as_pre_canonical(session_manager):
    """Only our own scheme marker is trusted; anything else takes the upgrade path."""
    with session_manager.engine.begin() as conn:
        conn.execute(
            text("UPDATE schema_migrations SET checksum=:c, checksum_scheme='source-text-v1' WHERE version=12"),
            {"c": "c" * 64},
        )
    verify_migration_checksums(session_manager.engine)
    rows = {m["version"]: m for m in get_applied_migrations(session_manager.engine)}
    assert rows[12]["checksum_scheme"] == CHECKSUM_SCHEME
    assert rows[12]["checksum"] != "c" * 64
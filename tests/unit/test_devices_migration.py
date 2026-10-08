"""Tribunal tests for migration 018: fresh install, verifier, and BigInteger capacity."""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from trace_core.core.database.migrations import (
    DEVICE_FINGERPRINTS_INDEX,
    DEVICE_FINGERPRINTS_TABLE,
    MIGRATION_OPERATIONS,
    MIGRATION_VERIFIERS,
    REQUIRED_DEVICE_COLUMNS,
    apply_migrations,
)

pytestmark = pytest.mark.unit

VERIFIER = MIGRATION_VERIFIERS[18]
HEAD = 18


@pytest.fixture
def fresh() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    return engine


@pytest.fixture
def empty() -> Engine:
    return create_engine("sqlite:///:memory:")


def test_the_registry_head_is_this_migration() -> None:
    from trace_core.core.database.migrations import MIGRATIONS

    assert max(version for version, _, _ in MIGRATIONS) == HEAD


def test_the_migration_declares_its_schema_effect() -> None:
    operations = MIGRATION_OPERATIONS[HEAD]
    assert any(DEVICE_FINGERPRINTS_TABLE in op for op in operations)
    assert any(DEVICE_FINGERPRINTS_INDEX in op for op in operations)


def test_a_fresh_database_ends_up_with_the_table(fresh: Engine) -> None:
    assert DEVICE_FINGERPRINTS_TABLE in inspect(fresh).get_table_names()


def test_a_fresh_database_ends_up_with_the_index(fresh: Engine) -> None:
    indexes = {idx["name"] for idx in inspect(fresh).get_indexes(DEVICE_FINGERPRINTS_TABLE)}
    assert DEVICE_FINGERPRINTS_INDEX in indexes


def test_a_fresh_database_records_the_migration(fresh: Engine) -> None:
    with fresh.begin() as conn:
        row = conn.execute(text(f"SELECT name FROM schema_migrations WHERE version = {HEAD}")).scalar()
    assert row == "018_create_device_fingerprints"


def test_every_declared_column_exists(fresh: Engine) -> None:
    columns = {col["name"] for col in inspect(fresh).get_columns(DEVICE_FINGERPRINTS_TABLE)}
    assert REQUIRED_DEVICE_COLUMNS.issubset(columns)
    missing = REQUIRED_DEVICE_COLUMNS - columns
    assert not missing, f"verifier would reject a table missing {missing}"


def test_the_verifier_passes_after_apply(fresh: Engine) -> None:
    with fresh.begin() as conn:
        assert VERIFIER(conn) is True


def test_the_verifier_rejects_a_missing_index(fresh: Engine) -> None:
    with fresh.begin() as conn:
        conn.execute(text(f"DROP INDEX {DEVICE_FINGERPRINTS_INDEX}"))
    with fresh.connect() as conn:
        assert VERIFIER(conn) is False


def test_the_verifier_rejects_a_missing_table(empty: Engine) -> None:
    with empty.connect() as conn:
        assert VERIFIER(conn) is False


def test_the_verifier_rejects_a_table_missing_a_column(fresh: Engine) -> None:
    with fresh.begin() as conn:
        conn.execute(text(f"ALTER TABLE {DEVICE_FINGERPRINTS_TABLE} DROP COLUMN unknown_cause"))
    with fresh.connect() as conn:
        assert VERIFIER(conn) is False


def test_capacity_beyond_int4_round_trips_exactly(fresh: Engine) -> None:
    huge = 9_007_199_254_740_993
    with fresh.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {DEVICE_FINGERPRINTS_TABLE} "
                "(id, node, serial, model, capacity_bytes, interface, source, inspected_at, inspected_by) "
                "VALUES (:id, :node, :serial, :model, :capacity, :interface, :source, :ts, :actor)"
            ),
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "node": "/dev/sda",
                "serial": "S1",
                "model": "M",
                "capacity": huge,
                "interface": "SATA",
                "source": "os",
                "ts": "2026-10-06 00:00:00",
                "actor": "operator@host",
            },
        )
        stored = conn.execute(text(f"SELECT capacity_bytes FROM {DEVICE_FINGERPRINTS_TABLE}")).scalar()
    assert stored == huge


def test_the_table_permits_a_repeated_serial(fresh: Engine) -> None:
    """[D3] append-only: a changed serial across inspections is itself evidence."""
    with fresh.begin() as conn:
        for index in ("1", "2"):
            conn.execute(
                text(
                    f"INSERT INTO {DEVICE_FINGERPRINTS_TABLE} "
                    "(id, node, serial, model, capacity_bytes, interface, source, inspected_at, inspected_by) "
                    "VALUES (:id, :node, :serial, :model, :capacity, :interface, :source, :ts, :actor)"
                ),
                {
                    "id": f"33333333-3333-3333-3333-33333333333{index}",
                    "node": "/dev/sda",
                    "serial": "S1",
                    "model": "M",
                    "capacity": 1024,
                    "interface": "SATA",
                    "source": "os",
                    "ts": "2026-10-06 00:00:00",
                    "actor": "operator@host",
                },
            )
        count = conn.execute(text(f"SELECT count(*) FROM {DEVICE_FINGERPRINTS_TABLE}")).scalar()
    assert count == 2


def test_the_table_carries_no_case_reference(fresh: Engine) -> None:
    """[D29] observation history outlives the case it was captured during."""
    columns = {col["name"] for col in inspect(fresh).get_columns(DEVICE_FINGERPRINTS_TABLE)}
    assert not any("case" in name for name in columns)


def test_migration_is_idempotent_on_reapplication(fresh: Engine) -> None:
    apply_migrations(fresh)
    with fresh.begin() as conn:
        assert VERIFIER(conn) is True
        count = conn.execute(text(f"SELECT count(*) FROM {DEVICE_FINGERPRINTS_TABLE}")).scalar()
    assert count == 0


def test_applying_to_a_database_that_predates_the_table_still_creates_it(empty: Engine) -> None:
    apply_migrations(empty)
    with empty.begin() as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {DEVICE_FINGERPRINTS_TABLE}")).scalar() == 0
        assert VERIFIER(conn) is True


def test_an_existing_head_17_database_gains_the_table_on_upgrade(fresh: Engine) -> None:
    """The real deployment path: 17 already applied, this migration is new."""
    with fresh.begin() as conn:
        conn.execute(text(f"DELETE FROM schema_migrations WHERE version = {HEAD}"))
        conn.execute(text(f"DROP TABLE {DEVICE_FINGERPRINTS_TABLE}"))
    with fresh.connect() as conn:
        assert DEVICE_FINGERPRINTS_TABLE not in inspect(conn).get_table_names()

    apply_migrations(fresh)
    with fresh.connect() as conn:
        assert DEVICE_FINGERPRINTS_TABLE in inspect(conn).get_table_names()
        assert DEVICE_FINGERPRINTS_INDEX in {i["name"] for i in inspect(conn).get_indexes(DEVICE_FINGERPRINTS_TABLE)}
        assert VERIFIER(conn) is True


def test_earlier_migrations_are_unaffected(fresh: Engine) -> None:
    from trace_core.core.database.migrations import MIGRATION_VERIFIERS as all_verifiers

    with fresh.connect() as conn:
        for version, verifier in all_verifiers.items():
            if version == HEAD:
                continue
            assert verifier(conn) is True, f"migration {version} verifier regressed"

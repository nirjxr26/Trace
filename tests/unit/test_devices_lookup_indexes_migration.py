"""Tribunal tests for migration 021: device lookup indexes on fresh and upgraded databases."""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from trace_core.core.database.migrations import (
    CASE_DEVICE_NODE_INDEX,
    DEVICE_FINGERPRINTS_TABLE,
    DEVICE_NODE_INDEX,
    DEVICE_OBSERVED_INDEX,
    MIGRATION_OPERATIONS,
    apply_migrations,
)

pytestmark = pytest.mark.unit

HEAD = 21


@pytest.fixture
def fresh() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    return engine


@pytest.fixture
def empty() -> Engine:
    return create_engine("sqlite:///:memory:")


def test_this_migration_is_registered() -> None:
    """021 must stay in the registry; later migrations build on it."""
    from trace_core.core.database.migrations import MIGRATIONS

    assert HEAD in {version for version, _, _ in MIGRATIONS}


def test_the_migration_declares_its_schema_effect() -> None:
    operations = MIGRATION_OPERATIONS[HEAD]
    assert any(DEVICE_NODE_INDEX in op for op in operations)
    assert any(DEVICE_OBSERVED_INDEX in op for op in operations)
    assert any(CASE_DEVICE_NODE_INDEX in op for op in operations)


def test_a_fresh_database_ends_up_with_the_indexes(fresh: Engine) -> None:
    fingerprints = {idx["name"] for idx in inspect(fresh).get_indexes(DEVICE_FINGERPRINTS_TABLE)}
    assert DEVICE_NODE_INDEX in fingerprints
    assert DEVICE_OBSERVED_INDEX in fingerprints
    links = {idx["name"] for idx in inspect(fresh).get_indexes("case_devices")}
    assert CASE_DEVICE_NODE_INDEX in links


def test_a_fresh_database_records_the_migration(fresh: Engine) -> None:
    with fresh.begin() as conn:
        row = conn.execute(text("SELECT name FROM schema_migrations WHERE version = 21")).scalar()
        assert row == "021_device_lookup_indexes"


def test_upgrade_adds_the_indexes_to_a_database_from_before(fresh: Engine) -> None:
    with fresh.begin() as conn:
        for table, name in (
            (DEVICE_FINGERPRINTS_TABLE, DEVICE_NODE_INDEX),
            (DEVICE_FINGERPRINTS_TABLE, DEVICE_OBSERVED_INDEX),
            ("case_devices", CASE_DEVICE_NODE_INDEX),
        ):
            conn.execute(text(f"DROP INDEX {name}"))
        conn.execute(text("DELETE FROM schema_migrations WHERE version = 21"))
    with fresh.connect() as conn:
        from trace_core.core.database.migrations import MIGRATION_VERIFIERS

        assert MIGRATION_VERIFIERS[HEAD](conn) is False
    apply_migrations(fresh)
    with fresh.connect() as conn:
        from trace_core.core.database.migrations import MIGRATION_VERIFIERS

        assert MIGRATION_VERIFIERS[HEAD](conn) is True
        plan = conn.exec_driver_sql("EXPLAIN QUERY PLAN SELECT * FROM device_fingerprints WHERE node = 'x'").all()
        assert any("USING INDEX" in str(row) for row in plan), plan


def test_hot_queries_stop_scanning(fresh: Engine) -> None:
    with fresh.connect() as conn:
        observed = conn.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT node,serial,model,capacity_bytes "
            "FROM device_fingerprints ORDER BY inspected_at DESC"
        ).all()
        assert not any("TEMP B-TREE" in str(row) for row in observed), observed
        by_node = conn.exec_driver_sql("SELECT * FROM device_fingerprints WHERE node = 'x'").all()
        _ = by_node
        plan = conn.exec_driver_sql("EXPLAIN QUERY PLAN SELECT * FROM device_fingerprints WHERE node = 'x'").all()
        assert any("USING INDEX" in str(row) for row in plan), plan
        links = conn.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT node FROM case_devices WHERE node = 'x' ORDER BY case_number"
        ).all()
        assert any("USING INDEX" in str(row) for row in links), links


def test_earlier_migrations_are_unaffected(fresh: Engine) -> None:
    from trace_core.core.database.migrations import MIGRATION_VERIFIERS as all_verifiers

    with fresh.connect() as conn:
        for version, verifier in all_verifiers.items():
            if version == HEAD:
                continue
            assert verifier(conn) is True, f"migration {version} verifier regressed"

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from trace_core.core.database.migrations import (
    AUDIT_DEVICE_SERIAL_ADD_COLUMN,
    AUDIT_DEVICE_SERIAL_ADD_INDEX,
    AUDIT_DEVICE_SERIAL_COLUMN,
    AUDIT_DEVICE_SERIAL_INDEX,
    MIGRATION_OPERATIONS,
    _column_allows_null,
    _column_names,
    _index_exists,
    _run_migration_022,
    _verify_022_audit_device_serial,
    apply_migrations,
)

pytestmark = pytest.mark.unit

HEAD = 22
TABLE = "audit_events"


@pytest.fixture
def fresh() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    return engine


def _drop_to_pre_022(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {AUDIT_DEVICE_SERIAL_INDEX}"))
        conn.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN {AUDIT_DEVICE_SERIAL_COLUMN}"))
        conn.execute(text(f"DELETE FROM schema_migrations WHERE version = {HEAD}"))


def test_this_migration_is_registered() -> None:
    from trace_core.core.database.migrations import MIGRATIONS

    assert HEAD in {version for version, _, _ in MIGRATIONS}


def test_the_migration_declares_its_schema_effect() -> None:
    assert MIGRATION_OPERATIONS[HEAD] == (AUDIT_DEVICE_SERIAL_ADD_COLUMN, AUDIT_DEVICE_SERIAL_ADD_INDEX)


def test_a_fresh_database_carries_the_column_and_its_index(fresh: Engine) -> None:
    with fresh.connect() as conn:
        assert AUDIT_DEVICE_SERIAL_COLUMN in _column_names(conn, TABLE)
        assert _index_exists(conn, TABLE, AUDIT_DEVICE_SERIAL_INDEX)
        assert _verify_022_audit_device_serial(conn) is True


def test_the_column_admits_null_so_pre_022_rows_survive(fresh: Engine) -> None:
    with fresh.connect() as conn:
        assert _column_allows_null(conn, TABLE, AUDIT_DEVICE_SERIAL_COLUMN)


def test_the_verifier_rejects_a_database_without_the_column(fresh: Engine) -> None:
    with fresh.begin() as conn:
        conn.execute(text(f"DROP INDEX {AUDIT_DEVICE_SERIAL_INDEX}"))
        conn.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN {AUDIT_DEVICE_SERIAL_COLUMN}"))
    with fresh.connect() as conn:
        assert _verify_022_audit_device_serial(conn) is False


def test_the_verifier_rejects_a_database_without_the_index(fresh: Engine) -> None:
    with fresh.begin() as conn:
        conn.execute(text(f"DROP INDEX {AUDIT_DEVICE_SERIAL_INDEX}"))
    with fresh.connect() as conn:
        assert _verify_022_audit_device_serial(conn) is False


def test_the_upgrade_adds_the_column_to_a_database_from_before_022(fresh: Engine) -> None:
    _drop_to_pre_022(fresh)
    with fresh.connect() as conn:
        assert _verify_022_audit_device_serial(conn) is False
    apply_migrations(fresh)
    with fresh.connect() as conn:
        assert AUDIT_DEVICE_SERIAL_COLUMN in _column_names(conn, TABLE)
        assert _index_exists(conn, TABLE, AUDIT_DEVICE_SERIAL_INDEX)
        assert _verify_022_audit_device_serial(conn) is True
        applied = conn.execute(text(f"SELECT count(*) FROM schema_migrations WHERE version = {HEAD}")).scalar()
    assert applied == 1


def test_running_the_upgrade_twice_is_harmless(fresh: Engine) -> None:
    with fresh.begin() as conn:
        _run_migration_022(conn)
        _run_migration_022(conn)
    with fresh.connect() as conn:
        assert _verify_022_audit_device_serial(conn) is True

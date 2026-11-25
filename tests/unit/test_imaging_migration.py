import pytest
from sqlalchemy import create_engine, inspect, text

from trace_core.core.database.migrations import MIGRATION_VERIFIERS, apply_migrations

pytestmark = pytest.mark.unit


def test_imaging_migration_creates_and_verifies_table() -> None:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)

    assert "imaging_operations" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert MIGRATION_VERIFIERS[26](connection)


def test_imaging_migration_verifier_rejects_missing_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_imaging_operations_case_id"))
        assert not MIGRATION_VERIFIERS[26](connection)


def test_imaging_migration_verifier_rejects_missing_case_number_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_imaging_operations_case_number"))
        assert not MIGRATION_VERIFIERS[26](connection)


def test_imaging_acquisition_migration_adds_columns_and_verifies() -> None:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("imaging_operations")}
    assert {"expected_bytes", "copied_bytes", "acquisition_sha256", "image_relpath", "manifest_relpath"} <= columns
    with engine.connect() as connection:
        assert MIGRATION_VERIFIERS[27](connection)


def test_imaging_acquisition_verifier_rejects_missing_state_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_imaging_operations_state"))
        assert not MIGRATION_VERIFIERS[27](connection)


def test_blocker_mode_migration_adds_column_and_default() -> None:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("imaging_operations")}
    assert "blocker_mode" in columns
    with engine.connect() as connection:
        assert MIGRATION_VERIFIERS[28](connection)


def test_blocker_mode_verifier_rejects_missing_column() -> None:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE imaging_operations DROP COLUMN blocker_mode"))
        assert not MIGRATION_VERIFIERS[28](connection)

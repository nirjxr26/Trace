import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from trace_core.core.database import migrations as mig
from trace_core.core.database.migrations import (
    DECOMMISSIONED_MIGRATIONS,
    MIGRATION_OPERATIONS,
    ROLE_DDL,
    _migration_checksum,
    _run_migration_025,
    _verify_025_least_privilege_roles,
    apply_migrations,
)

pytestmark = pytest.mark.unit

HEAD = 25
DECOMMISSIONED = 11


@pytest.fixture
def fresh() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    return engine


def _explode(_conn: object) -> None:
    raise RuntimeError("boom: permission denied to create role")


def test_this_migration_is_registered() -> None:
    assert HEAD in {version for version, _, _ in mig.MIGRATIONS}


def test_the_migration_declares_the_role_ddl_as_its_schema_effect() -> None:
    assert MIGRATION_OPERATIONS[HEAD] == tuple(ROLE_DDL)


def test_011_is_decommissioned_with_a_reason() -> None:
    assert DECOMMISSIONED in DECOMMISSIONED_MIGRATIONS
    assert "025" in DECOMMISSIONED_MIGRATIONS[DECOMMISSIONED]


def test_the_decommissioned_identity_is_unchanged(fresh: Engine) -> None:
    """H-58: 011 stays recorded under its original canonical identity, so deployed
    databases that already applied it can never see a checksum drift from this change."""
    with fresh.connect() as conn:
        recorded = conn.execute(
            text("SELECT name, checksum FROM schema_migrations WHERE version = :v"), {"v": DECOMMISSIONED}
        ).one()
    assert recorded[0] == "011_create_least_privilege_roles"
    assert recorded[1] == _migration_checksum(DECOMMISSIONED, recorded[0])


def test_a_decommissioned_action_is_skipped_and_still_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """H-58: 011's CREATE ROLE blocks every later migration on managed PostgreSQL; the
    recorded-not-run path must let the chain complete even when the action would raise."""
    engine = create_engine("sqlite:///:memory:")
    replaced = [
        (version, name, _explode if version == DECOMMISSIONED else action) for version, name, action in mig.MIGRATIONS
    ]
    monkeypatch.setattr(mig, "MIGRATIONS", replaced)

    apply_migrations(engine)

    with engine.connect() as conn:
        applied = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
    assert applied == {version for version, _, _ in replaced}
    assert applied >= {DECOMMISSIONED, HEAD}


def test_a_fresh_database_applies_the_replacement_and_verifies(fresh: Engine) -> None:
    with fresh.connect() as conn:
        applied = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        assert HEAD in applied
        assert _verify_025_least_privilege_roles(conn) is True


def test_running_the_replacement_twice_is_harmless(fresh: Engine) -> None:
    with fresh.begin() as conn:
        _run_migration_025(conn)
        _run_migration_025(conn)
    with fresh.connect() as conn:
        assert _verify_025_least_privilege_roles(conn) is True

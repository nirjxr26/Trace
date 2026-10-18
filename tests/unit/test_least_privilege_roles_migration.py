from types import SimpleNamespace

import pytest
import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from trace_core.core.database import migrations as mig
from trace_core.core.database.migrations import (
    DECOMMISSIONED_MIGRATIONS,
    MIGRATION_OPERATIONS,
    ROLE_DDL,
    _migration_checksum,
    _run_migration_025,
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


def test_011_is_decommissioned() -> None:
    assert DECOMMISSIONED in DECOMMISSIONED_MIGRATIONS


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


def test_a_connecting_role_without_createrole_is_skipped_with_one_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """H-58: on managed PostgreSQL the connecting role may lack CREATEROLE; the
    pre-check must report it once and let the rest of the chain record and continue."""
    captured: list[dict] = []

    class _Log:
        def warning(self, event: str, **kwargs: object) -> None:
            captured.append({"event": event, **kwargs})

    class _Result:
        def scalar(self) -> bool:
            return False

    class _PgConn:
        dialect = SimpleNamespace(name="postgresql")

        def execute(self, _stmt: object) -> _Result:
            return _Result()

    monkeypatch.setattr(structlog, "get_logger", lambda: _Log())
    _run_migration_025(_PgConn())  # type: ignore[arg-type]

    assert len(captured) == 1
    assert captured[0]["event"] == "Skipping least-privilege role setup: the connecting role cannot create roles"


def test_a_fresh_database_applies_the_resilient_replacement(fresh: Engine) -> None:
    with fresh.connect() as conn:
        applied = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
    assert HEAD in applied


def test_running_the_replacement_twice_is_harmless(fresh: Engine) -> None:
    with fresh.begin() as conn:
        _run_migration_025(conn)
        _run_migration_025(conn)

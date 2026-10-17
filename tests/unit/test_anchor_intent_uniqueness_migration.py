import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from trace_core.audit.models import AnchorIntentModel
from trace_core.core.database.migrations import (
    ANCHOR_INTENT_UNIQUE_ADD_INDEX,
    ANCHOR_INTENT_UNIQUE_INDEX,
    MIGRATION_OPERATIONS,
    _run_migration_024,
    _verify_024_anchor_intent_uniqueness,
    apply_migrations,
)

pytestmark = pytest.mark.unit

HEAD = 24
TABLE = "anchor_intents"


@pytest.fixture
def fresh() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    apply_migrations(engine)
    return engine


def _drop_to_pre_024(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {ANCHOR_INTENT_UNIQUE_INDEX}"))
        conn.execute(text(f"DELETE FROM schema_migrations WHERE version = {HEAD}"))


def _insert_duplicate_intents(engine: Engine) -> None:
    with Session(engine) as session:
        session.add_all(
            [
                AnchorIntentModel(case_number="2026-DUP-0001", seq=7, chain_hash="0" * 64),
                AnchorIntentModel(case_number="2026-DUP-0001", seq=7, chain_hash="0" * 64),
            ]
        )
        session.commit()


def test_this_migration_is_registered() -> None:
    from trace_core.core.database.migrations import MIGRATIONS

    assert HEAD in {version for version, _, _ in MIGRATIONS}


def test_the_migration_declares_its_schema_effect() -> None:
    assert MIGRATION_OPERATIONS[HEAD] == (ANCHOR_INTENT_UNIQUE_ADD_INDEX,)


def test_a_fresh_database_carries_the_unique_index(fresh: Engine) -> None:
    with fresh.connect() as conn:
        assert _verify_024_anchor_intent_uniqueness(conn) is True
        unique = {idx["name"]: idx.get("unique") for idx in inspect(conn).get_indexes(TABLE)}
    assert bool(unique.get(ANCHOR_INTENT_UNIQUE_INDEX)) is True


def test_the_verifier_rejects_a_database_without_the_unique_index(fresh: Engine) -> None:
    with fresh.begin() as conn:
        conn.execute(text(f"DROP INDEX {ANCHOR_INTENT_UNIQUE_INDEX}"))
    with fresh.connect() as conn:
        assert _verify_024_anchor_intent_uniqueness(conn) is False


def test_the_verifier_rejects_a_non_unique_index_wearing_the_reserved_name(fresh: Engine) -> None:
    with fresh.begin() as conn:
        conn.execute(text(f"DROP INDEX {ANCHOR_INTENT_UNIQUE_INDEX}"))
        conn.execute(text(f"CREATE INDEX {ANCHOR_INTENT_UNIQUE_INDEX} ON {TABLE} (case_number, seq)"))
    with fresh.connect() as conn:
        assert _verify_024_anchor_intent_uniqueness(conn) is False


def test_the_upgrade_refuses_duplicates_keeps_every_row_and_stays_unrecorded(fresh: Engine) -> None:
    _drop_to_pre_024(fresh)
    _insert_duplicate_intents(fresh)

    with pytest.raises(RuntimeError, match=r"2026-DUP-0001 seq 7 x2"):
        apply_migrations(fresh)

    with fresh.connect() as conn:
        kept = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar()
        recorded = conn.execute(text(f"SELECT count(*) FROM schema_migrations WHERE version = {HEAD}")).scalar()
    assert kept == 2
    assert recorded == 0


def test_the_upgrade_succeeds_after_the_duplicate_is_resolved_by_hand(fresh: Engine) -> None:
    _drop_to_pre_024(fresh)
    _insert_duplicate_intents(fresh)
    with pytest.raises(RuntimeError):
        apply_migrations(fresh)

    with fresh.begin() as conn:
        doomed = conn.execute(text(f"SELECT id FROM {TABLE} LIMIT 1")).scalar()
        conn.execute(text(f"DELETE FROM {TABLE} WHERE id = :i"), {"i": doomed})

    apply_migrations(fresh)
    with fresh.connect() as conn:
        assert _verify_024_anchor_intent_uniqueness(conn) is True
        recorded = conn.execute(text(f"SELECT count(*) FROM schema_migrations WHERE version = {HEAD}")).scalar()
    assert recorded == 1


def test_the_upgrade_adds_the_index_to_a_database_from_before_024(fresh: Engine) -> None:
    _drop_to_pre_024(fresh)
    with fresh.connect() as conn:
        assert _verify_024_anchor_intent_uniqueness(conn) is False

    apply_migrations(fresh)

    with fresh.connect() as conn:
        assert _verify_024_anchor_intent_uniqueness(conn) is True


def test_running_the_upgrade_twice_is_harmless(fresh: Engine) -> None:
    with fresh.begin() as conn:
        _run_migration_024(conn)
        _run_migration_024(conn)
    with fresh.connect() as conn:
        assert _verify_024_anchor_intent_uniqueness(conn) is True

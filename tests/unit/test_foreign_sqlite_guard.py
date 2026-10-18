import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from trace_core.core.database.migrations import apply_migrations
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import ApplicationError

pytestmark = pytest.mark.unit


def _foreign_database(path: Path, table: str = "invoices") -> None:
    """A non-empty SQLite file that is not Trace: one table, no schema_migrations."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, amount INTEGER)"))
    engine.dispose()


def _table_names(path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        names = set(inspect(conn).get_table_names())
    engine.dispose()
    return names


def test_an_existing_sqlite_database_that_is_not_trace_is_refused(tmp_path: Path) -> None:
    """H-63: a typo'd TRACE_DATABASE_URL must not be migrated into."""
    db = tmp_path / "foreign.db"
    _foreign_database(db)
    mgr = DatabaseSessionManager(f"sqlite:///{db}")

    with pytest.raises(ApplicationError, match="Refusing to initialize this database"):
        mgr.ensure_ready()


def test_the_refused_file_is_left_byte_identical(tmp_path: Path) -> None:
    """The guard runs before any write: same bytes, no added tables, no journal sidecars."""
    db = tmp_path / "foreign.db"
    _foreign_database(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    with pytest.raises(ApplicationError):
        apply_migrations(create_engine(f"sqlite:///{db}"))

    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert _table_names(db) == {"invoices"}
    assert not list(tmp_path.glob("foreign.db-*")), "no journal or sidecar may be left behind"


def test_a_database_with_tables_but_no_migration_table_is_refused(tmp_path: Path) -> None:
    """A cases table without schema_migrations is not identifiable as a Trace database."""
    db = tmp_path / "half.db"
    _foreign_database(db, table="cases")

    with pytest.raises(ApplicationError, match="Refusing to initialize this database"):
        apply_migrations(create_engine(f"sqlite:///{db}"))


def test_an_empty_sqlite_file_is_migrated_normally(tmp_path: Path) -> None:
    """A fresh, empty file is a legitimate first run and must still install."""
    db = tmp_path / "empty.db"
    db.touch()
    mgr = DatabaseSessionManager(f"sqlite:///{db}")

    mgr.ensure_ready()

    tables = _table_names(db)
    assert "schema_migrations" in tables
    assert "cases" in tables


def test_an_existing_trace_database_is_reopened_not_refused(tmp_path: Path) -> None:
    """The guard recognizes Trace by schema_migrations; a second apply is a no-op."""
    db = tmp_path / "trace.db"
    apply_migrations(create_engine(f"sqlite:///{db}"))

    apply_migrations(create_engine(f"sqlite:///{db}"))

    tables = _table_names(db)
    assert "schema_migrations" in tables
    assert "cases" in tables

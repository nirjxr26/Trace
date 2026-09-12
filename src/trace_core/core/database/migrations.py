"""Lightweight schema migration management and version tracking."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Connection, DateTime, Engine, Integer, MetaData, String, Table, inspect, select, text

from trace_core.core.clock import now_utc
from trace_core.core.database.base import Base

metadata = MetaData()

# Schema migrations table definition
schema_migrations = Table(
    "schema_migrations",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False, default=now_utc),
)

MigrationAction = Callable[[Engine | Connection], None]

# Migration registry: (version, name, action)
MIGRATIONS: list[tuple[int, str, MigrationAction]] = []


def register_migration(version: int, name: str) -> Callable[[MigrationAction], MigrationAction]:
    """Decorator to register a schema migration."""

    def decorator(fn: MigrationAction) -> MigrationAction:
        MIGRATIONS.append((version, name, fn))
        MIGRATIONS.sort(key=lambda m: m[0])
        return fn

    return decorator


@register_migration(1, "001_initial_case_schema")
def _migration_001_initial_schema(bind: Engine | Connection) -> None:
    """Initial schema migration: creates core and case tables."""
    import trace_core.cases.models  # noqa: F401

    Base.metadata.create_all(bind=bind)


_CASE_COLUMN_DEFINITIONS = (
    ("closed_by", "ALTER TABLE cases ADD COLUMN closed_by VARCHAR(255)"),
    ("closure_reason", "ALTER TABLE cases ADD COLUMN closure_reason TEXT"),
    ("archived_at", "ALTER TABLE cases ADD COLUMN archived_at TIMESTAMP WITH TIME ZONE"),
    ("version", "ALTER TABLE cases ADD COLUMN version INTEGER NOT NULL DEFAULT 1"),
)


def _apply_missing_columns(conn: Connection, existing_cols: set[str]) -> None:
    for col_name, ddl in _CASE_COLUMN_DEFINITIONS:
        if col_name not in existing_cols:
            conn.execute(text(ddl))


@register_migration(2, "002_add_concurrency_and_closure_columns")
def _migration_002_add_columns(bind: Engine | Connection) -> None:
    """Add closure metadata, archived_at, and OCC version columns to existing tables."""
    inspector = inspect(bind)
    if "cases" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("cases")}
        if isinstance(bind, Connection):
            _apply_missing_columns(bind, cols)
        else:
            with bind.begin() as conn:
                _apply_missing_columns(conn, cols)

    # Ensure any new tables (e.g. case_sequences) are created
    Base.metadata.create_all(bind=bind)


@register_migration(3, "003_create_case_sequences_table")
def _migration_003_case_sequences(bind: Engine | Connection) -> None:
    """Create case_sequences table for atomic sequence allocation."""
    import trace_core.cases.models  # noqa: F401

    if "case_sequences" in Base.metadata.tables:
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["case_sequences"]])


def ensure_migration_table(engine: Engine) -> None:
    """Create schema_migrations tracking table if it does not exist."""
    schema_migrations.create(bind=engine, checkfirst=True)


def get_applied_migrations(engine: Engine) -> list[dict[str, Any]]:
    """Return list of all applied migration records."""
    ensure_migration_table(engine)
    with engine.connect() as conn:
        stmt = select(
            schema_migrations.c.version,
            schema_migrations.c.name,
            schema_migrations.c.applied_at,
        ).order_by(schema_migrations.c.version.asc())
        rows = conn.execute(stmt).fetchall()
        return [
            {
                "version": r[0],
                "name": r[1],
                "applied_at": r[2] if isinstance(r[2], datetime) else None,
            }
            for r in rows
        ]


def get_pending_migrations(engine: Engine) -> list[tuple[int, str]]:
    """Return list of migrations not yet applied to the database."""
    applied_versions = {m["version"] for m in get_applied_migrations(engine)}
    return [(v, name) for v, name, _ in MIGRATIONS if v not in applied_versions]


def apply_migrations(engine: Engine) -> list[str]:
    """Apply all pending migrations sequentially within transaction boundaries."""
    ensure_migration_table(engine)
    applied_versions = {m["version"] for m in get_applied_migrations(engine)}
    applied_names: list[str] = []

    for version, name, action in MIGRATIONS:
        if version not in applied_versions:
            with engine.begin() as conn:
                action(conn)
                conn.execute(
                    schema_migrations.insert().values(
                        version=version,
                        name=name,
                        applied_at=now_utc(),
                    )
                )
            applied_names.append(name)

    return applied_names


def get_table_names(engine: Engine) -> list[str]:
    """Inspect and return existing database table names."""
    inspector = inspect(engine)
    return inspector.get_table_names()

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
    Column("checksum", String(64), nullable=True),
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
    ("archived_by", "ALTER TABLE cases ADD COLUMN archived_by VARCHAR(255)"),
    ("version", "ALTER TABLE cases ADD COLUMN version INTEGER NOT NULL DEFAULT 1"),
)


def _ensure_column(conn: Connection, table: str, column: str, ddl: str) -> None:
    """Add a column via DDL when it does not exist yet. Shared by backfill paths."""
    if column not in _column_names(conn, table):
        conn.execute(text(ddl))


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


@register_migration(4, "004_add_archived_by_column")
def _migration_004_archived_by(bind: Engine | Connection) -> None:
    """Backfill archived_by for databases that applied 002 before it existed."""
    inspector = inspect(bind)
    if "cases" not in inspector.get_table_names():
        return
    ddl = "ALTER TABLE cases ADD COLUMN archived_by VARCHAR(255)"
    if isinstance(bind, Connection):
        _ensure_column(bind, "cases", "archived_by", ddl)
    else:
        with bind.begin() as conn:
            _ensure_column(conn, "cases", "archived_by", ddl)


@register_migration(5, "005_create_audit_ledger")
def _migration_005_audit(bind: Engine | Connection) -> None:
    """Create tamper-evident audit ledger and serialized chain head."""
    import trace_core.audit.models  # noqa: F401

    Base.metadata.create_all(
        bind=bind,
        tables=[
            Base.metadata.tables["audit_chain_state"],
            Base.metadata.tables["audit_events"],
        ],
    )

    if isinstance(bind, Connection):
        _seed_audit_chain_state(bind)
        _install_sqlite_audit_triggers(bind)


@register_migration(6, "006_add_case_checks")
def _migration_006_case_checks(bind: Engine | Connection) -> None:
    """Add forensic CHECKs for status/version. Idempotent, best-effort on SQLite."""

    def _try(conn: Connection, ddl: str) -> None:
        try:
            conn.execute(text(ddl))
        except Exception:
            pass

    if isinstance(bind, Connection):
        _try(bind, "ALTER TABLE cases ADD CHECK (status IN ('OPEN','UNDER_REVIEW','CLOSED'))")
        _try(bind, "ALTER TABLE cases ADD CHECK (version >= 1)")
    else:
        with bind.begin() as conn:
            _try(conn, "ALTER TABLE cases ADD CHECK (status IN ('OPEN','UNDER_REVIEW','CLOSED'))")
            _try(conn, "ALTER TABLE cases ADD CHECK (version >= 1)")


@register_migration(7, "007_add_perf_indexes")
def _migration_007_perf_indexes(bind: Engine | Connection) -> None:
    """Add perf indexes for audit case+seq and cases examiner. Idempotent."""

    def _try_idx(conn: Connection, ddl: str) -> None:
        try:
            conn.execute(text(ddl))
        except Exception:
            pass

    idx_cases = "CREATE INDEX IF NOT EXISTS idx_cases_lead_examiner_is_deleted ON cases (lead_examiner, is_deleted)"
    idx_audit = "CREATE INDEX IF NOT EXISTS idx_audit_case_seq ON audit_events (subject_case_number, seq DESC)"
    if isinstance(bind, Connection):
        if "cases" in inspect(bind).get_table_names():
            _try_idx(bind, idx_cases)
        if "audit_events" in inspect(bind).get_table_names():
            _try_idx(bind, idx_audit)
    else:
        with bind.begin() as conn:
            tables = inspect(conn).get_table_names()
            if "cases" in tables:
                _try_idx(conn, idx_cases)
            if "audit_events" in tables:
                _try_idx(conn, idx_audit)


def _seed_audit_chain_state(conn: Connection) -> None:
    """Seed the chain head when it does not already exist."""
    row = conn.execute(text("SELECT id FROM audit_chain_state WHERE id=1")).fetchone()
    if row:
        return
    conn.execute(
        text("INSERT INTO audit_chain_state (id, last_seq, last_chain_hash) VALUES (1, 0, :h)"),
        {"h": "0" * 64},
    )


def _install_sqlite_audit_triggers(conn: Connection) -> None:
    """Install append-only audit triggers for SQLite connections."""
    if conn.dialect.name != "sqlite":
        return
    for ddl in (
        "DROP TRIGGER IF EXISTS audit_events_no_update",
        "DROP TRIGGER IF EXISTS audit_events_no_delete",
        "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END",
        "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END",
    ):
        try:
            conn.execute(text(ddl))
        except Exception:
            pass


def _migration_checksum(name: str) -> str:
    """Compute stable checksum for migration bookkeeping."""
    import hashlib

    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _index_exists(conn: Connection, table: str, index: str) -> bool:
    return any(idx["name"] == index for idx in inspect(conn).get_indexes(table))


def _column_names(conn: Connection, table: str) -> set[str]:
    """Return column names for a table via inspector."""
    return {c["name"] for c in inspect(conn).get_columns(table)}


def ensure_migration_table(engine: Engine) -> None:
    """Create schema_migrations tracking table if it does not exist."""
    schema_migrations.create(bind=engine, checkfirst=True)
    with engine.begin() as conn:
        _ensure_column(
            conn, "schema_migrations", "checksum", "ALTER TABLE schema_migrations ADD COLUMN checksum VARCHAR(64)"
        )


def get_applied_migrations(engine: Engine) -> list[dict[str, Any]]:
    """Return list of all applied migration records."""
    ensure_migration_table(engine)
    with engine.connect() as conn:
        cols = _column_names(conn, "schema_migrations")
        if "checksum" in cols:
            stmt = select(
                schema_migrations.c.version,
                schema_migrations.c.name,
                schema_migrations.c.applied_at,
                schema_migrations.c.checksum,
            ).order_by(schema_migrations.c.version.asc())
        else:
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
                "checksum": r[3] if len(r) > 3 else None,
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
                cols = _column_names(conn, "schema_migrations")
                values: dict[str, Any] = {
                    "version": version,
                    "name": name,
                    "applied_at": now_utc(),
                }
                if "checksum" in cols:
                    values["checksum"] = _migration_checksum(name)
                conn.execute(schema_migrations.insert().values(**values))
            applied_names.append(name)

    return applied_names


def get_table_names(engine: Engine) -> list[str]:
    """Inspect and return existing database table names."""
    inspector = inspect(engine)
    return inspector.get_table_names()

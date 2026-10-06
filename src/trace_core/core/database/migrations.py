"""Lightweight schema migration management and version tracking."""

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Connection, Engine, Integer, MetaData, String, Table, inspect, select, text

from trace_core.core.clock import now_utc
from trace_core.core.database.base import Base, UTCDateTime

metadata = MetaData()

# Schema migrations table definition
schema_migrations = Table(
    "schema_migrations",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("applied_at", UTCDateTime, nullable=False, default=now_utc),
    Column("checksum", String(64), nullable=True),
    Column("checksum_scheme", String(32), nullable=True),
)

MigrationAction = Callable[[Engine | Connection], None]
MigrationVerifier = Callable[[Connection], bool]

# Identity scheme for the recorded checksum. Rows carrying anything else predate
# canonical migration identity and are upgraded once, explicitly, on first run.
CHECKSUM_SCHEME = "canonical-v2"

DEVICE_FINGERPRINTS_TABLE = "device_fingerprints"
DEVICE_FINGERPRINTS_INDEX = "ix_device_fingerprints_identity"
REQUIRED_DEVICE_COLUMNS = frozenset(
    {
        "id",
        "node",
        "serial",
        "model",
        "capacity_bytes",
        "firmware",
        "interface",
        "wwn",
        "source",
        "verdict",
        "unknown_cause",
        "evidence",
        "inspected_at",
        "inspected_by",
    }
)

# Migration registry: (version, name, action)
MIGRATIONS: list[tuple[int, str, MigrationAction]] = []

# Declared schema operations per version. This is what the checksum commits to —
# never the Python source. A comment, a reformat, or a decorator rewrite leaves it
# untouched, while a genuine change to what a migration does changes it.
MIGRATION_OPERATIONS: dict[int, tuple[str, ...]] = {}

# Post-action verifiers: run inside the same transaction; False aborts without recording.
# Production rule: run migration → verify resulting schema → record on success, abort on failure.
MIGRATION_VERIFIERS: dict[int, MigrationVerifier] = {}


def register_migration(
    version: int,
    name: str,
    operations: tuple[str, ...],
    verify: MigrationVerifier | None = None,
) -> Callable[[MigrationAction], MigrationAction]:
    """Register a migration. `operations` is its declared schema effect and is mandatory.

    Required rather than optional so no migration can be registered without a
    declared identity; there is no source-text fallback left to regress into.
    """

    def decorator(fn: MigrationAction) -> MigrationAction:
        # A duplicate version is silent and unrecoverable: apply_migrations sorts by
        # version, so the later registration replaces the earlier one's verifier and
        # only one ever runs, while schema_migrations records both as applied.
        if any(existing == version or existing_name == name for existing, existing_name, _ in MIGRATIONS):
            raise RuntimeError(f"duplicate migration {version}/{name}; version and name must both be unique")
        MIGRATIONS.append((version, name, fn))
        MIGRATIONS.sort(key=lambda m: m[0])
        MIGRATION_OPERATIONS[version] = operations
        if verify is not None:
            MIGRATION_VERIFIERS[version] = verify
        _assert_registry_is_linear()
        return fn

    return decorator


def _assert_registry_is_linear() -> None:
    """Versions must be 1..N with no gaps. Deleting a migration forked history silently:
    an already-migrated DB kept its row and never applied the missing one, while a fresh DB
    skipped it entirely — two different schemas, no error on either. Registrations must also
    be appended in order, so a migration is never inserted above ones already applied.
    """
    versions = [version for version, _, _ in MIGRATIONS]
    expected = list(range(1, len(versions) + 1))
    if versions != expected:
        raise RuntimeError(f"migration versions must be contiguous 1..{len(versions)}; got {versions}")


def _create_all(tables: tuple[str, ...]) -> str:
    return f"create_all:{','.join(tables)}"


@register_migration(1, "001_initial_case_schema", operations=(_create_all(("*",)),))
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


@register_migration(
    2,
    "002_add_concurrency_and_closure_columns",
    operations=tuple(ddl for _, ddl in _CASE_COLUMN_DEFINITIONS) + (_create_all(("*",)),),
)
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


@register_migration(3, "003_create_case_sequences_table", operations=(_create_all(("case_sequences",)),))
def _migration_003_case_sequences(bind: Engine | Connection) -> None:
    """Create case_sequences table for atomic sequence allocation."""
    import trace_core.cases.models  # noqa: F401

    if "case_sequences" in Base.metadata.tables:
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["case_sequences"]])


@register_migration(
    4,
    "004_add_archived_by_column",
    operations=("ALTER TABLE cases ADD COLUMN archived_by VARCHAR(255)",),
)
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


@register_migration(
    5,
    "005_create_audit_ledger",
    operations=(
        _create_all(("audit_chain_state", "audit_events")),
        "seed audit_chain_state",
        "install sqlite append-only triggers",
    ),
)
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


@register_migration(
    6,
    "006_add_case_checks",
    operations=(
        "ALTER TABLE cases ADD CHECK (status IN ('OPEN','UNDER_REVIEW','CLOSED'))",
        "ALTER TABLE cases ADD CHECK (version >= 1)",
    ),
    verify=lambda conn: _verify_006_case_checks(conn),
)
def _migration_006_case_checks(bind: Engine | Connection) -> None:
    """Add forensic CHECKs for status/version. PostgreSQL-only; SQLite enforces the same
    rules in the domain layer (SQLite has no ALTER TABLE ADD CHECK)."""

    def _run(conn: Connection) -> None:
        if conn.dialect.name != "postgresql":
            return
        for ddl in (
            "ALTER TABLE cases ADD CHECK (status IN ('OPEN','UNDER_REVIEW','CLOSED'))",
            "ALTER TABLE cases ADD CHECK (version >= 1)",
        ):
            try:
                conn.execute(text(ddl))
            except Exception:
                pass  # idempotent re-run; the verifier below is the honesty gate

    if isinstance(bind, Connection):
        _run(bind)
    else:
        with bind.begin() as conn:
            _run(conn)


def _verify_006_case_checks(conn: Connection) -> bool:
    """Confirm both CHECKs exist on PostgreSQL; vacuously true on SQLite (see parity table)."""
    if conn.dialect.name != "postgresql":
        return True
    count = conn.execute(
        text("SELECT count(*) FROM pg_constraint WHERE conrelid = 'cases'::regclass AND contype = 'c'")
    ).scalar()
    return (count or 0) >= 2


@register_migration(
    7,
    "007_add_perf_indexes",
    operations=(
        "CREATE INDEX IF NOT EXISTS idx_cases_lead_examiner_is_deleted ON cases (lead_examiner, is_deleted)",
        "CREATE INDEX IF NOT EXISTS idx_audit_case_seq ON audit_events (subject_case_number, seq DESC)",
    ),
)
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


@register_migration(
    8,
    "008_audit_append_only_protection",
    operations=(
        "install postgresql audit_events append-only trigger",
        "install sqlite audit_events append-only triggers",
    ),
    verify=lambda conn: _verify_008_audit_protection(conn),
)
def _migration_008_audit_protection(bind: Engine | Connection) -> None:
    """Enforce the append-only ledger per backend: PostgreSQL trigger plus SQLite
    trigger self-heal (005 installed them; this guarantees them on every database)."""
    if isinstance(bind, Connection):
        _install_pg_audit_trigger(bind)
        _install_sqlite_audit_triggers(bind)
    else:
        with bind.begin() as conn:
            _install_pg_audit_trigger(conn)
            _install_sqlite_audit_triggers(conn)


PG_AUDIT_TRUNCATE_TRIGGER_DDL = (
    "CREATE TRIGGER audit_events_no_truncate "
    "BEFORE TRUNCATE ON audit_events "
    "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_block_write()"
)


def _install_pg_audit_trigger(conn: Connection) -> None:
    """Install append-only audit trigger for PostgreSQL connections."""
    if conn.dialect.name != "postgresql":
        return
    conn.execute(
        text(
            "CREATE OR REPLACE FUNCTION audit_events_block_write() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_events is append-only'; END; $$ LANGUAGE plpgsql"
        )
    )
    conn.execute(text("DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events"))
    conn.execute(
        text(
            "CREATE TRIGGER audit_events_no_update_delete "
            "BEFORE UPDATE OR DELETE ON audit_events "
            "FOR EACH ROW EXECUTE FUNCTION audit_events_block_write()"
        )
    )
    # TRUNCATE fires no row-level DELETE trigger: statement-level backstop.
    conn.execute(text("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events"))
    conn.execute(text(PG_AUDIT_TRUNCATE_TRIGGER_DDL))


def _verify_008_audit_protection(conn: Connection) -> bool:
    """Confirm append-only protection exists on the current backend."""
    if conn.dialect.name == "postgresql":
        count = conn.execute(
            text("SELECT count(*) FROM pg_trigger WHERE tgrelid = 'audit_events'::regclass AND NOT tgisinternal")
        ).scalar()
        return (count or 0) >= 1
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit_events'")
    ).fetchall()
    return {"audit_events_no_update", "audit_events_no_delete"} <= {r[0] for r in rows}


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


def _migration_checksum(version: int, name: str) -> str:
    """Canonical identity digest: scheme, version, name, declared operations.

    Never hashes Python source. The previous scheme did, so a comment, a reformat,
    or any rewrite of the @register_migration line changed the digest and hard-failed
    every deployed install with no escape hatch. What a migration *does* is declared
    as data and hashed canonically; how it is formatted is not part of its identity.
    """
    import hashlib

    from trace_core.core.canonical import canonical_json

    payload = {
        "scheme": CHECKSUM_SCHEME,
        "version": version,
        "name": name,
        "operations": list(MIGRATION_OPERATIONS.get(version, ())),
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def verify_migration_checksums(engine: Engine) -> list[dict[str, Any]]:
    """Fail closed on canonical-identity drift; upgrade pre-canonical rows once.

    Controlled upgrade path: a row whose scheme marker is absent or older predates
    canonical migration identity. Its old digest was a source-text hash we can no
    longer meaningfully reproduce, so it is re-recorded once with the scheme set,
    under a warning. From then on the digest is compared strictly. This also means
    the scheme change itself cannot brick a deployed database, which is the property
    the old scheme lacked.
    """
    import structlog

    records = get_applied_migrations(engine)
    upgrades: list[tuple[int, str, str]] = []
    for record in records:
        expected = _migration_checksum(record["version"], record["name"])
        if record.get("checksum_scheme") == CHECKSUM_SCHEME:
            if record["checksum"] != expected:
                raise RuntimeError(
                    f"Migration {record['name']} declared operations drifted from the recorded "
                    "canonical identity; refusing to proceed."
                )
            continue
        upgrades.append((record["version"], record["name"], expected))
    if upgrades:
        structlog.get_logger().warning(
            "Upgrading migration checksum bookkeeping to canonical identity",
            migrations=[name for _, name, _ in upgrades],
        )
        with engine.begin() as conn:
            for version, _name, expected in upgrades:
                conn.execute(
                    schema_migrations.update()
                    .where(schema_migrations.c.version == version)
                    .values(checksum=expected, checksum_scheme=CHECKSUM_SCHEME)
                )
        for record in records:
            record["checksum_scheme"] = CHECKSUM_SCHEME
    return records


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
        _ensure_column(
            conn,
            "schema_migrations",
            "checksum_scheme",
            "ALTER TABLE schema_migrations ADD COLUMN checksum_scheme VARCHAR(32)",
        )


def get_applied_migrations(engine: Engine) -> list[dict[str, Any]]:
    """Return list of all applied migration records."""
    ensure_migration_table(engine)
    with engine.connect() as conn:
        cols = _column_names(conn, "schema_migrations")
        has_checksum = "checksum" in cols
        has_scheme = "checksum_scheme" in cols
        selected = [schema_migrations.c.version, schema_migrations.c.name, schema_migrations.c.applied_at]
        if has_checksum:
            selected.append(schema_migrations.c.checksum)
        if has_scheme:
            selected.append(schema_migrations.c.checksum_scheme)
        stmt = select(*selected).order_by(schema_migrations.c.version.asc())
        rows = conn.execute(stmt).fetchall()
        return [
            {
                "version": r[0],
                "name": r[1],
                "applied_at": r[2] if isinstance(r[2], datetime) else None,
                "checksum": r[3] if has_checksum else None,
                "checksum_scheme": r[4] if has_scheme else None,
            }
            for r in rows
        ]


def get_pending_migrations(engine: Engine) -> list[tuple[int, str]]:
    """Return list of migrations not yet applied to the database."""
    applied_versions = {m["version"] for m in get_applied_migrations(engine)}
    return [(v, name) for v, name, _ in MIGRATIONS if v not in applied_versions]


@contextmanager
def _migration_lock(engine: Engine):  # type: ignore[no-untyped-def]
    """Serialize concurrent bootstraps: PG advisory lock, SQLite lockfile, else no-op."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('trace_schema_migrations'))"))
            yield
        return
    lock_path = _sqlite_lock_path(str(engine.url))
    if lock_path is None:
        yield
        return
    with _file_lock(lock_path):
        yield


def _sqlite_lock_path(url: str) -> str | None:
    """Lockfile beside a file-backed SQLite database; None for :memory:."""
    import os

    from trace_core.core.database.session import sqlite_file_path

    path = sqlite_file_path(url)
    if path is None:
        return None
    if not path.is_absolute():
        path = Path(os.path.abspath(path))
    return str(path) + ".migratelock"


@contextmanager
def _file_lock(path: str):  # type: ignore[no-untyped-def]
    """Blocking exclusive lockfile. Windows msvcrt, POSIX fcntl."""
    from trace_core.core.fs import file_lock

    with file_lock(path):
        yield


def apply_migrations(engine: Engine) -> list[str]:
    """Apply all pending migrations sequentially within transaction boundaries."""
    with _migration_lock(engine):
        ensure_migration_table(engine)
        applied_versions = {m["version"] for m in verify_migration_checksums(engine)}
        applied_names: list[str] = []

        for version, name, action in MIGRATIONS:
            if version not in applied_versions:
                with engine.begin() as conn:
                    action(conn)
                    verifier = MIGRATION_VERIFIERS.get(version)
                    if verifier is not None and not verifier(conn):
                        raise RuntimeError(f"Migration {name} failed verification; rolled back, not recorded.")
                    cols = _column_names(conn, "schema_migrations")
                    values: dict[str, Any] = {
                        "version": version,
                        "name": name,
                        "applied_at": now_utc(),
                    }
                    if "checksum" in cols:
                        values["checksum"] = _migration_checksum(version, name)
                    if "checksum_scheme" in cols:
                        values["checksum_scheme"] = CHECKSUM_SCHEME
                    conn.execute(schema_migrations.insert().values(**values))
                applied_names.append(name)

        return applied_names


def get_table_names(engine: Engine) -> list[str]:
    """Inspect and return existing database table names."""
    inspector = inspect(engine)
    return inspector.get_table_names()


@register_migration(9, "009_create_purged_numbers_tombstone", operations=(_create_all(("purged_numbers",)),))
def _migration_009_purged_numbers(bind: Engine | Connection) -> None:
    """Tombstone purged case numbers so they can never be re-registered."""
    import trace_core.cases.models  # noqa: F401

    if "purged_numbers" in Base.metadata.tables:
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["purged_numbers"]])


ROLE_DDL: tuple[str, ...] = (
    # Least privilege, PostgreSQL only. Roles are NOLOGIN: operators grant LOGIN
    # with their own passwords separately. Safe re-runs (IF NOT EXISTS / NOTICE).
    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trace_app') "
    "THEN CREATE ROLE trace_app NOLOGIN; END IF; END $$",
    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trace_reader') "
    "THEN CREATE ROLE trace_reader NOLOGIN; END IF; END $$",
    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trace_migrator') "
    "THEN CREATE ROLE trace_migrator NOLOGIN; END IF; END $$",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON cases, case_sequences, purged_numbers TO trace_app",
    "GRANT SELECT, INSERT ON audit_events, audit_chain_state TO trace_app",
    "REVOKE UPDATE, DELETE, TRUNCATE ON audit_events, audit_chain_state FROM trace_app",
    "REVOKE UPDATE, DELETE, TRUNCATE ON schema_migrations FROM trace_app",
    "GRANT SELECT ON cases, case_sequences, purged_numbers, audit_events, audit_chain_state,"
    " schema_migrations TO trace_reader",
)


@register_migration(
    10,
    "010_add_ledger_signature_columns",
    operations=(
        "ALTER TABLE audit_events ADD COLUMN key_id VARCHAR(64)",
        "ALTER TABLE audit_events ADD COLUMN signature VARCHAR(128)",
    ),
)
def _migration_010_signature(bind: Engine | Connection) -> None:
    """HMAC envelope columns for ledger authenticity (nullable: legacy rows verify chain-only)."""
    cols = (
        ("key_id", "ALTER TABLE audit_events ADD COLUMN key_id VARCHAR(64)"),
        ("signature", "ALTER TABLE audit_events ADD COLUMN signature VARCHAR(128)"),
    )
    if isinstance(bind, Connection):
        for col_name, ddl in cols:
            _ensure_column(bind, "audit_events", col_name, ddl)
    else:
        with bind.begin() as conn:
            for col_name, ddl in cols:
                _ensure_column(conn, "audit_events", col_name, ddl)


@register_migration(11, "011_create_least_privilege_roles", operations=ROLE_DDL)
def _migration_011_roles(bind: Engine | Connection) -> None:
    """Create NOLOGIN app/reader/migrator roles and revoke ledger mutation. PostgreSQL only."""
    if isinstance(bind, Connection):
        if bind.dialect.name != "postgresql":
            return
        for stmt in ROLE_DDL:
            bind.execute(text(stmt))
    else:
        with bind.begin() as conn:
            if conn.dialect.name != "postgresql":
                return
            for stmt in ROLE_DDL:
                conn.execute(text(stmt))


@register_migration(12, "012_create_operators_table", operations=(_create_all(("operators",)),))
def _migration_012_operators(bind: Engine | Connection) -> None:
    """Operator registry for workstation RBAC (auto-provisioned, first-ever is admin)."""
    import trace_core.core.operators  # noqa: F401

    if "operators" in Base.metadata.tables:
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["operators"]])


@register_migration(13, "013_create_anchor_intents_outbox", operations=(_create_all(("anchor_intents",)),))
def _migration_013_anchor_intents(bind: Engine | Connection) -> None:
    """Durable anchor outbox so closes never report anchors that were never written."""
    import trace_core.audit.models  # noqa: F401

    if "anchor_intents" in Base.metadata.tables:
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["anchor_intents"]])


@register_migration(14, "014_create_update_history", operations=(_create_all(("update_history",)),))
def _migration_014_update_history(bind: Engine | Connection) -> None:
    # The update_history model is gone; the table is only kept for databases that already
    # applied 014–016. A fresh install never creates it, and the migration stays in place
    # because the registry enforces contiguity.
    if "update_history" in Base.metadata.tables:
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["update_history"]])


@register_migration(
    15,
    "015_update_history_provenance",
    operations=(
        "ALTER TABLE update_history ADD COLUMN backup_path TEXT",
        "ALTER TABLE update_history ADD COLUMN override_reason TEXT",
    ),
)
def _migration_015_update_provenance(bind: Engine | Connection) -> None:
    for column, ddl in (
        ("backup_path", "ALTER TABLE update_history ADD COLUMN backup_path TEXT"),
        ("override_reason", "ALTER TABLE update_history ADD COLUMN override_reason TEXT"),
    ):
        if isinstance(bind, Connection):
            if "update_history" in inspect(bind).get_table_names():
                _ensure_column(bind, "update_history", column, ddl)
        else:
            with bind.begin() as conn:
                if "update_history" in inspect(conn).get_table_names():
                    _ensure_column(conn, "update_history", column, ddl)


def _safe_nested_execute(conn: Connection, stmt: str) -> None:
    try:
        with conn.begin_nested():
            conn.execute(text(stmt))
    except Exception:
        pass


def _migration_016_ensure_columns(conn: Connection, cols: set[str]) -> None:
    bool_default = "FALSE" if conn.dialect.name == "postgresql" else "0"
    for column, ddl in (
        ("artifact_sha256", "ALTER TABLE update_history ADD COLUMN artifact_sha256 VARCHAR(64)"),
        ("signing_key_id", "ALTER TABLE update_history ADD COLUMN signing_key_id VARCHAR(64)"),
        ("failure_reason", "ALTER TABLE update_history ADD COLUMN failure_reason TEXT"),
        (
            "restart_required",
            f"ALTER TABLE update_history ADD COLUMN restart_required BOOLEAN DEFAULT {bool_default}",
        ),
    ):
        if column not in cols:
            _safe_nested_execute(conn, ddl)


def _migration_016_ensure_indexes(conn: Connection) -> None:
    for idx_name, col in (
        ("ix_update_history_transaction_id", "transaction_id"),
        ("ix_update_history_started_at", "started_at"),
    ):
        if not _index_exists(conn, "update_history", idx_name):
            _safe_nested_execute(conn, f"CREATE INDEX {idx_name} ON update_history ({col})")


def _run_migration_016(conn: Connection) -> None:
    if "update_history" not in inspect(conn).get_table_names():
        return
    cols = _column_names(conn, "update_history")
    _migration_016_ensure_columns(conn, cols)
    bool_lit = "FALSE" if conn.dialect.name == "postgresql" else "0"
    _safe_nested_execute(conn, f"UPDATE update_history SET restart_required={bool_lit} WHERE restart_required IS NULL")
    _safe_nested_execute(conn, f"UPDATE update_history SET rollback={bool_lit} WHERE rollback IS NULL")
    _migration_016_ensure_indexes(conn)


@register_migration(
    16,
    "016_update_history_roundtrip",
    operations=(
        "ALTER TABLE update_history ADD COLUMN artifact_sha256 VARCHAR(64)",
        "ALTER TABLE update_history ADD COLUMN signing_key_id VARCHAR(64)",
        "ALTER TABLE update_history ADD COLUMN failure_reason TEXT",
        "ALTER TABLE update_history ADD COLUMN restart_required BOOLEAN",
        "backfill restart_required/rollback from NULL",
        "CREATE INDEX ix_update_history_transaction_id ON update_history (transaction_id)",
        "CREATE INDEX ix_update_history_started_at ON update_history (started_at)",
    ),
)
def _migration_016_update_roundtrip(bind: Engine | Connection) -> None:
    """History round-trip: transaction index + provenance columns for read DTO parity."""
    if isinstance(bind, Connection):
        _run_migration_016(bind)
    else:
        with bind.begin() as conn:
            _run_migration_016(conn)


SUBJECT_TYPE_COLUMN = "subject_type"
SUBJECT_TYPE_INDEX = "ix_audit_events_subject_type"
AUDIT_EVENTS_REBUILD_TABLE = "_audit_events_d14"


def _column_allows_null(conn: Connection, table: str, column: str) -> bool:
    for col in inspect(conn).get_columns(table):
        if col["name"] == column:
            return bool(col["nullable"])
    return False


def _drop_audit_write_triggers(conn: Connection) -> None:
    if conn.dialect.name == "postgresql":
        for ddl in (
            "DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events",
            "DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events",
        ):
            conn.execute(text(ddl))
        return
    for ddl in (
        "DROP TRIGGER IF EXISTS audit_events_no_update",
        "DROP TRIGGER IF EXISTS audit_events_no_delete",
    ):
        conn.execute(text(ddl))


def _install_audit_write_triggers(conn: Connection) -> None:
    _install_pg_audit_trigger(conn)
    _install_sqlite_audit_triggers(conn)


def _sqlite_rebuild_audit_events(conn: Connection) -> None:
    """SQLite cannot DROP NOT NULL, so the table is rebuilt from the model definition.

    Existing index DDL and data are preserved verbatim; the append-only triggers are
    reinstalled by the caller because a rebuild drops them.
    """
    from sqlalchemy import MetaData
    from sqlalchemy.schema import CreateTable

    import trace_core.audit.models  # noqa: F401

    saved_indexes = [
        (row[0], row[1])
        for row in conn.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='audit_events' AND sql IS NOT NULL"
            )
        ).fetchall()
    ]
    old_columns = {c["name"] for c in inspect(conn).get_columns("audit_events")}
    rebuilt = Base.metadata.tables["audit_events"].to_metadata(MetaData(), name=AUDIT_EVENTS_REBUILD_TABLE)
    conn.execute(text(str(CreateTable(rebuilt).compile(dialect=conn.dialect))))
    shared = [c.name for c in rebuilt.columns if c.name in old_columns]
    column_list = ", ".join(shared)
    conn.execute(
        text(f"INSERT INTO {AUDIT_EVENTS_REBUILD_TABLE} ({column_list}) SELECT {column_list} FROM audit_events")
    )
    conn.execute(text("DROP TABLE audit_events"))
    conn.execute(text(f"ALTER TABLE {AUDIT_EVENTS_REBUILD_TABLE} RENAME TO audit_events"))
    for _name, ddl in saved_indexes:
        conn.execute(text(ddl))


def _run_migration_017(conn: Connection) -> None:
    if "audit_events" not in inspect(conn).get_table_names():
        return
    columns = _column_names(conn, "audit_events")
    is_sqlite = conn.dialect.name == "sqlite"
    if SUBJECT_TYPE_COLUMN not in columns:
        conn.execute(text(f"ALTER TABLE audit_events ADD COLUMN {SUBJECT_TYPE_COLUMN} VARCHAR(32)"))

    _drop_audit_write_triggers(conn)
    try:
        conn.execute(
            text(f"UPDATE audit_events SET {SUBJECT_TYPE_COLUMN} = 'case' WHERE {SUBJECT_TYPE_COLUMN} IS NULL")
        )
        if is_sqlite:
            _sqlite_rebuild_audit_events(conn)
        else:
            conn.execute(text("ALTER TABLE audit_events ALTER COLUMN subject_case_number DROP NOT NULL"))
            conn.execute(text(f"ALTER TABLE audit_events ALTER COLUMN {SUBJECT_TYPE_COLUMN} SET NOT NULL"))
    finally:
        _install_audit_write_triggers(conn)

    if not _index_exists(conn, "audit_events", SUBJECT_TYPE_INDEX):
        conn.execute(text(f"CREATE INDEX {SUBJECT_TYPE_INDEX} ON audit_events ({SUBJECT_TYPE_COLUMN})"))


def _verify_017_audit_subject_type(conn: Connection) -> bool:
    if "audit_events" not in inspect(conn).get_table_names():
        return True
    columns = _column_names(conn, "audit_events")
    if SUBJECT_TYPE_COLUMN not in columns:
        return False
    unlabelled = conn.execute(text(f"SELECT count(*) FROM audit_events WHERE {SUBJECT_TYPE_COLUMN} IS NULL")).scalar()
    if unlabelled:
        return False
    if not _column_allows_null(conn, "audit_events", "subject_case_number"):
        return False
    if _column_allows_null(conn, "audit_events", SUBJECT_TYPE_COLUMN):
        return False
    return _verify_008_audit_protection(conn)


@register_migration(
    17,
    "017_audit_subject_type",
    operations=(
        "ALTER TABLE audit_events ADD COLUMN subject_type VARCHAR(32)",
        "backfill audit_events.subject_type from NULL to 'case'",
        "relax audit_events.subject_case_number to nullable",
        "restore audit_events append-only triggers after backfill",
        "CREATE INDEX ix_audit_events_subject_type ON audit_events (subject_type)",
    ),
    verify=lambda conn: _verify_017_audit_subject_type(conn),
)
def _migration_017_audit_subject_type(bind: Engine | Connection) -> None:
    """Give every audit row an explicit subject type and allow a subject with no case."""
    if isinstance(bind, Connection):
        _run_migration_017(bind)
    else:
        with bind.begin() as conn:
            _run_migration_017(conn)


def _verify_018_device_fingerprints(conn: Connection) -> bool:
    if DEVICE_FINGERPRINTS_TABLE not in inspect(conn).get_table_names():
        return False
    if not REQUIRED_DEVICE_COLUMNS.issubset(_column_names(conn, DEVICE_FINGERPRINTS_TABLE)):
        return False
    return _index_exists(conn, DEVICE_FINGERPRINTS_TABLE, DEVICE_FINGERPRINTS_INDEX)


@register_migration(
    18,
    "018_create_device_fingerprints",
    operations=(
        _create_all((DEVICE_FINGERPRINTS_TABLE,)),
        f"CREATE INDEX {DEVICE_FINGERPRINTS_INDEX} on device_fingerprints (serial, inspected_at)",
    ),
    verify=lambda conn: _verify_018_device_fingerprints(conn),
)
def _migration_018_device_fingerprints(bind: Engine | Connection) -> None:
    """Device observation history. Append-only, never purged with a case [D3], [D29].

    The model module is imported here because `Base.metadata` only holds tables whose
    model has been imported; without it a fresh database would migrate to 18 and then
    find no table. `create_all` also builds the index, so it is declared for the
    checksum and re-checked by the verifier rather than created a second time.
    """
    import trace_core.devices.models  # noqa: F401

    if DEVICE_FINGERPRINTS_TABLE not in Base.metadata.tables:
        return
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[DEVICE_FINGERPRINTS_TABLE]])

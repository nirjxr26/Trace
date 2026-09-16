"""Single source for DB health snapshots shared by CLI status and TUI database tab."""

from dataclasses import dataclass, field


@dataclass
class DbSnapshot:
    """Raw DB health data. Callers own rendering (CLI table vs TUI cards)."""

    healthy: bool
    message: str
    masked_url: str
    tables: list[str] = field(default_factory=list)
    applied: list[dict] = field(default_factory=list)
    pending: list[tuple] = field(default_factory=list)


def fetch_db_snapshot(mgr=None):  # type: ignore[no-untyped-def]
    """Check connection + tables + migrations. Never raises on connection failure."""
    from trace_core.core.database.migrations import (
        get_applied_migrations,
        get_pending_migrations,
        get_table_names,
    )
    from trace_core.core.database.session import db_manager, sanitized_db_url
    from trace_core.core.settings import settings

    manager = mgr or db_manager
    try:
        healthy, message = manager.check_connection()
    except Exception as exc:
        healthy, message = False, str(exc)
    masked = sanitized_db_url(settings.database_url)
    if not healthy:
        return DbSnapshot(healthy=False, message=message, masked_url=masked)
    tables = get_table_names(manager.engine)
    applied = get_applied_migrations(manager.engine)
    pending = get_pending_migrations(manager.engine)
    return DbSnapshot(
        healthy=True,
        message=message,
        masked_url=masked,
        tables=tables,
        applied=applied,
        pending=pending,
    )


def migration_entries(applied: list[dict], pending: list[tuple]) -> list[tuple]:
    """Sorted (version, name, status, applied_at) rows shared by CLI and TUI tables."""
    applied_by_ver = {m["version"]: m for m in applied}
    pending_by_ver = {v: n for v, n in pending}
    entries = []
    for version in sorted(set(applied_by_ver) | set(pending_by_ver)):
        if version in applied_by_ver:
            m = applied_by_ver[version]
            entries.append((version, m["name"], "Applied", m.get("applied_at")))
        else:
            entries.append((version, pending_by_ver[version], "Pending", None))
    return entries

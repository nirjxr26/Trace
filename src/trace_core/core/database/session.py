"""Database engine factory and session management."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from trace_core.core.settings import settings


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create a configured SQLAlchemy engine."""
    url = database_url or settings.database_url

    connect_args: dict[str, Any] = {}
    engine_kwargs: dict[str, Any] = {
        "echo": settings.sql_echo,
    }

    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        engine = create_engine(url, connect_args=connect_args, **engine_kwargs)

        # Enable WAL mode and foreign keys for SQLite
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    # PostgreSQL / other production DBs
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10
    return create_engine(url, connect_args=connect_args, **engine_kwargs)


_READY_CACHE: dict[str, bool] = {}


class DatabaseSessionManager:
    """Manages database engine, schema creation, and sessions."""

    def __init__(self, database_url: str | None = None):
        self._url = database_url or settings.database_url
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_db_engine(self._url)
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autoflush=False,
                expire_on_commit=False,
            )
        return self._session_factory

    def check_connection(self) -> tuple[bool, str]:
        """Verify database connectivity. Returns (is_healthy, status_message)."""
        from sqlalchemy import text

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, "Database connection successful"
        except Exception as exc:
            import structlog

            structlog.get_logger().warning("Database connection failed", error=str(exc))
            return False, "Connection failed: database unreachable. Check service status or TRACE_DATABASE_URL."

    def init_schema(self) -> None:
        """Create database tables and apply pending migrations."""
        from trace_core.core.database.migrations import apply_migrations

        apply_migrations(self.engine)

    def ensure_ready(self) -> None:
        from trace_core.updates.migration import is_owner, marker_state

        state, active = marker_state()
        if state == "corrupt":
            from trace_core.updates.errors import UpdateInProgressError

            raise UpdateInProgressError("update marker unreadable; run trace recovery before starting")
        if state == "active" and active is not None and not is_owner(str(active.get("transaction_id"))):
            from trace_core.updates.errors import UpdateInProgressError

            raise UpdateInProgressError(
                f"update transaction {active.get('transaction_id')} owns migration; normal startup deferred"
            )
        memory = ":memory:" in self._url
        if not memory and _READY_CACHE.get(self._url):
            return
        from trace_core.core.database.migrations import apply_migrations

        apply_migrations(self.engine)
        if not memory:
            _READY_CACHE[self._url] = True

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context-managed session providing transaction boundary."""
        self.ensure_ready()
        session = self.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def sanitized_db_identity(url: str) -> str:
    """Stable database identity without credentials. Safe for cache keys and logs."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        user = parts.username or ""
        return f"{parts.scheme}://{user}@{host}{parts.path or ''}"
    except Exception:
        return "unknown"


def sanitized_db_url(url: str) -> str:
    """Full database URL with the password masked. Single source for display."""
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(url)
        if not parts.hostname:
            return url
        hostport = parts.hostname
        if parts.port:
            hostport += f":{parts.port}"
        if parts.username and parts.password:
            netloc = f"{parts.username}:*****@{hostport}"
        elif parts.username:
            netloc = f"*****@{hostport}"
        else:
            return url
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return url


def db_identity(manager: DatabaseSessionManager | None = None) -> str:
    """Short stable identity for cache keys. Never includes credentials."""
    import hashlib

    try:
        url = manager._url if manager is not None else settings.database_url
        clean = sanitized_db_identity(url)
    except Exception:
        clean = "unknown"
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


def get_db(ctx: Any | None) -> DatabaseSessionManager:  # type: ignore[no-untyped-def]
    """Single source for DB manager from shell context or global. Reusable."""
    try:
        mgr = getattr(getattr(ctx, "service", None), "session_manager", None)
        if mgr is not None:
            return mgr  # type: ignore[no-any-return]
    except Exception:
        pass
    return db_manager


# Default global instance configured with application settings
db_manager = DatabaseSessionManager()

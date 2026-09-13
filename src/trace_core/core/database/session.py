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
        "echo": settings.debug,
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
            return False, f"Connection failed: {exc}"

    def init_schema(self) -> None:
        """Create database tables and apply pending migrations."""
        from trace_core.core.database.migrations import apply_migrations

        apply_migrations(self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context-managed session providing transaction boundary."""
        session = self.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


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

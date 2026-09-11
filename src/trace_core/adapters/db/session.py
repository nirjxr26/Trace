"""Database engine factory and session management."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from trace_core.adapters.db.models import Base
from trace_core.settings import settings


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

    # PostgreSQL / other DBs
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

    def _ensure_postgres_database(self) -> None:
        """If target PostgreSQL database does not exist, connect to postgres maintenance db and create it."""
        from sqlalchemy import text
        from sqlalchemy.engine import make_url

        try:
            url_obj = make_url(self._url)
            target_db = url_obj.database
            if not target_db or target_db == "postgres":
                return

            maint_url = url_obj.set(database="postgres")
            maint_engine = create_engine(maint_url, isolation_level="AUTOCOMMIT")
            with maint_engine.connect() as conn:
                check_stmt = text("SELECT 1 FROM pg_database WHERE datname = :dbname")
                result = conn.execute(check_stmt, {"dbname": target_db}).scalar()
                if not result:
                    conn.execute(text(f'CREATE DATABASE "{target_db}"'))
            maint_engine.dispose()
        except Exception:
            # Let standard connection errors surface during normal engine connection
            pass

    def init_schema(self) -> None:
        """Create database tables if they do not exist."""
        if "postgres" in self._url.lower():
            self._ensure_postgres_database()
        Base.metadata.create_all(bind=self.engine)

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


# Default global instance configured with application settings
db_manager = DatabaseSessionManager()

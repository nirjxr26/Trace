"""Base application service definitions."""

from trace_core.core.database.session import DatabaseSessionManager, db_manager


class BaseService:
    """Base application service managing database session life-cycle."""

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        self.session_manager = session_manager or db_manager

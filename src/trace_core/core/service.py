"""Base application service definitions with transactional unit-of-work."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from trace_core.core.database.session import DatabaseSessionManager, db_manager


class UnitOfWork:
    """Encapsulates a database session and post-commit event/audit hooks."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.post_commit_hooks: list[Callable[[], Any]] = []

    def on_commit(self, hook: Callable[[], Any]) -> None:
        """Register an event or audit hook to execute after transaction commit."""
        self.post_commit_hooks.append(hook)


class BaseService:
    """Base application service managing database session lifecycle and audit boundaries."""

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        self.session_manager = session_manager or db_manager

    @contextmanager
    def transaction(self) -> Generator[UnitOfWork, None, None]:
        """Transactional Unit-of-Work boundary supporting post-commit event/audit dispatch."""
        with self.session_manager.session() as session:
            uow = UnitOfWork(session)
            yield uow
            session.commit()
            for hook in uow.post_commit_hooks:
                hook()

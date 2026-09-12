"""Base application service definitions with transactional unit-of-work."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from trace_core.core.database.session import DatabaseSessionManager, db_manager


class UnitOfWork:
    """Encapsulates a database session with distinct transactional (pre-commit) and post-commit hook boundaries.

    Forensic Invariant (P0-2):
    - Mandatory forensic records (e.g. AuditEvent) MUST execute within the database transaction
      (either directly on the session or via `before_commit`). If audit logging fails, the transaction
      must roll back, ensuring case mutations never persist without corresponding audit entries.
    - `on_commit` hooks are strictly reserved for non-critical, optional external side-effects
      (e.g., telemetry, cache eviction, desktop notifications) that only fire after commit succeeds.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.before_commit_hooks: list[Callable[[Session], Any]] = []
        self.post_commit_hooks: list[Callable[[], Any]] = []

    def before_commit(self, hook: Callable[[Session], Any]) -> None:
        """Register a mandatory hook executed inside the transaction boundary before commit.

        If the hook raises an exception, the entire transaction is rolled back.
        """
        self.before_commit_hooks.append(hook)

    def on_commit(self, hook: Callable[[], Any]) -> None:
        """Register an optional side-effect hook executed strictly after transaction commit succeeds."""
        self.post_commit_hooks.append(hook)


class BaseService:
    """Base application service managing database session lifecycle and audit boundaries."""

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        self.session_manager = session_manager or db_manager

    @contextmanager
    def transaction(self) -> Generator[UnitOfWork, None, None]:
        """Transactional Unit-of-Work boundary enforcing pre-commit hooks before commit and post-commit side effects."""
        with self.session_manager.session() as session:
            uow = UnitOfWork(session)
            yield uow

            # Execute mandatory pre-commit hooks within the transaction
            for pre_hook in uow.before_commit_hooks:
                pre_hook(session)

            session.commit()

            # Execute optional external side effects only after successful commit
            for post_hook in uow.post_commit_hooks:
                post_hook()

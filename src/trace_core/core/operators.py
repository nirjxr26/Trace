"""Operator registry and role enforcement. Single source for workstation identity.

Model: operators self-provision on first use (name + host). The FIRST operator
ever recorded is admin (fresh-workstation bootstrap); everyone after is
investigator. Auditors read and verify only. Roles are enforced in the service
layer so CLI, REPL, and TUI share one gate. No login infrastructure exists yet:
this binds permissions to OS identity, which raises the bar from anonymous
self-assertion to workstation accountability without pretending to be login.
"""

import getpass
import socket
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from trace_core.core.clock import now_utc
from trace_core.core.database.base import Base
from trace_core.core.errors import ApplicationError, AuthorizationError

ROLE_INVESTIGATOR = "investigator"
ROLE_AUDITOR = "auditor"
ROLE_ADMIN = "admin"
STATUS_ACTIVE = "active"
DEFAULT_ACTION = "perform this action"

_SESSION_ID = uuid.uuid4().hex[:12]


def process_session_id() -> str:
    """Stable id for this process. Groups events; proves nothing about login."""
    return _SESSION_ID


class OperatorModel(Base):
    """Workstation operator with a role. Auto-provisioned, never self-promoted."""

    __tablename__ = "operators"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_INVESTIGATOR, nullable=False)
    public_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (UniqueConstraint("name", "host", name="uq_operators_name_host"),)


def current_identity() -> tuple[str, str]:
    """OS user + host. Metadata for attribution, never proof of login."""
    try:
        user = getpass.getuser() or "unknown"
    except Exception:
        user = "unknown"
    try:
        host = socket.gethostname() or "unknown"
    except Exception:
        host = "unknown"
    return user, host


def _missing_table(exc: Exception) -> bool:
    return "no such table" in str(exc).lower() or getattr(getattr(exc, "orig", None), "pgcode", None) == "42P01"


def get_or_provision(session: Session, name: str, host: str) -> OperatorModel:
    """Fetch the operator row, creating it (first-ever becomes admin)."""
    from sqlalchemy import select

    try:
        existing = session.scalar(select(OperatorModel).where(OperatorModel.name == name, OperatorModel.host == host))
    except Exception as exc:
        if _missing_table(exc):
            raise ApplicationError("Operator store not initialized. Run 'trace db migrate'.") from exc
        raise
    if existing is not None:
        return existing
    first_ever = session.scalar(select(OperatorModel.id).limit(1)) is None
    row = OperatorModel(name=name, host=host, role=ROLE_ADMIN if first_ever else ROLE_INVESTIGATOR)
    try:
        # Savepoint, not rollback: a race must never nuke the caller's transaction.
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        # Concurrent first-use race: someone else provisioned (possibly as admin); take theirs.
        existing = session.scalar(select(OperatorModel).where(OperatorModel.name == name, OperatorModel.host == host))
        if existing is None:
            raise
        return existing
    return row


def current_operator(session: Session) -> OperatorModel:
    """Operator for this process. Auto-provisions on first mutating use."""
    name, host = current_identity()
    return get_or_provision(session, name, host)


def require_role(session: Session, *roles: str, action: str = DEFAULT_ACTION) -> OperatorModel:
    """Enforce roles for one operation. Inactive operators are always denied."""
    operator = current_operator(session)
    if operator.status != STATUS_ACTIVE or operator.role not in roles:
        raise AuthorizationError(f"Operator '{operator.name}' with role '{operator.role}' may not {action}.")
    return operator


def require_admin(session: Session, action: str = DEFAULT_ACTION) -> OperatorModel:
    """Admin-only gate for destructive or key operations."""
    return require_role(session, ROLE_ADMIN, action=action)


def require_mutator(session: Session, action: str = DEFAULT_ACTION) -> OperatorModel:
    """Investigator-or-admin gate for case mutations. Auditors are read-only."""
    return require_role(session, ROLE_INVESTIGATOR, ROLE_ADMIN, action=action)

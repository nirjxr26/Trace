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

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from trace_core.core.clock import now_utc
from trace_core.core.database.base import Base, UTCDateTime
from trace_core.core.database.session import DatabaseSessionManager
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc, nullable=False)

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


def find_operator(session: Session, name: str, host: str) -> OperatorModel | None:
    """Resolve an operator by identity, or None if never provisioned. SELECT only."""
    try:
        return session.scalar(select(OperatorModel).where(OperatorModel.name == name, OperatorModel.host == host))
    except Exception as exc:
        from trace_core.core.database.health import is_missing_relation_error

        if is_missing_relation_error(exc):
            raise ApplicationError("Operator store not initialized. Run `trace db migrate`.") from exc
        raise


def get_or_provision_operator(session: Session, name: str, host: str) -> OperatorModel:
    """Fetch the operator row, inserting it when absent (first-ever becomes admin). Caller owns the COMMIT."""
    existing = find_operator(session, name, host)
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
        winner = find_operator(session, name, host)
        if winner is None:
            raise
        return winner
    return row


def current_operator(session: Session) -> OperatorModel:
    """Operator for this process. Auto-provisions on first mutating use."""
    name, host = current_identity()
    return get_or_provision_operator(session, name, host)


def bootstrap_current_operator(session_manager: DatabaseSessionManager) -> OperatorModel | None:
    """Provision this identity on its own committed session. Returns the new row, or None if it already existed."""
    name, host = current_identity()
    with session_manager.session() as session:
        if find_operator(session, name, host) is not None:
            return None
        operator = get_or_provision_operator(session, name, host)
        session.commit()
        return operator


def require_role(session: Session, *roles: str, action: str = DEFAULT_ACTION) -> OperatorModel:
    """Enforce roles for one operation. Inactive operators are always denied.

    Roles are compared normalised so a stored `Admin ` or `admin` still matches,
    matching the .upper() convention every other lookup in this codebase uses.
    """
    name, host = current_identity()
    operator = find_operator(session, name, host)
    if operator is None:
        raise AuthorizationError(f"Operator '{name}' on '{host}' is not provisioned and may not {action}.")
    if operator.status != STATUS_ACTIVE or operator.role.upper() not in {r.upper() for r in roles}:
        raise AuthorizationError(f"Operator '{operator.name}' with role '{operator.role}' may not {action}.")
    return operator


def require_admin(session: Session, action: str = DEFAULT_ACTION) -> OperatorModel:
    """Admin-only gate for destructive or key operations."""
    return require_role(session, ROLE_ADMIN, action=action)


def require_mutator(session: Session, action: str = DEFAULT_ACTION) -> OperatorModel:
    """Investigator-or-admin gate for case mutations. Auditors are read-only."""
    return require_role(session, ROLE_INVESTIGATOR, ROLE_ADMIN, action=action)

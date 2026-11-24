from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import AuthorizationError
from trace_core.core.operators import STATUS_ACTIVE, current_identity, find_operator


def active_operator(manager: DatabaseSessionManager):  # type: ignore[no-untyped-def]
    name, host = current_identity()
    with manager.session() as session:
        operator = find_operator(session, name, host)
        if operator is None:
            raise AuthorizationError("Operator is not provisioned and may not use the MCP server.")
        if operator.status != STATUS_ACTIVE:
            raise AuthorizationError("Operator is not active and may not use the MCP server.")
        return operator


def operator_summary(manager: DatabaseSessionManager) -> dict[str, str]:
    operator = active_operator(manager)
    return {"name": operator.name, "host": operator.host, "role": operator.role}

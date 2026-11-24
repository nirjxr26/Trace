import json
import time
import uuid

import structlog
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError

from trace_core.audit.builder import command_context
from trace_core.mcp.errors import map_error
from trace_core.mcp.identity import active_operator
from trace_core.mcp.server import ServerContext


def _resource(ctx: ServerContext, name: str, operation):  # type: ignore[no-untyped-def]
    correlation_id = uuid.uuid4().hex
    started = time.monotonic()
    operator = "unknown"
    outcome = "ok"
    error_code = ""
    logger = structlog.get_logger()
    try:
        with command_context(f"mcp resource {name}"):
            operator_row = active_operator(ctx.session_manager)
            operator = f"{operator_row.name}@{operator_row.host}"
            return json.dumps(operation(), ensure_ascii=False, separators=(",", ":"))
    except Exception as exc:
        outcome = "error"
        mapped = map_error(exc, correlation_id)
        error_code = mapped["code"]
        raise ResourceError(f"{error_code}: {mapped['message']} [{correlation_id}]") from None
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "mcp_resource_read",
            resource=name,
            correlation_id=correlation_id,
            operator=operator,
            duration_ms=duration_ms,
            outcome=outcome,
            error_code=error_code,
        )


def register(server: MCPServer, ctx: ServerContext) -> None:
    from trace_core.mcp.tools.audit import _get as audit_get
    from trace_core.mcp.tools.audit import _list as audit_list
    from trace_core.mcp.tools.cases import _get as case_get
    from trace_core.mcp.tools.devices import _history as device_history
    from trace_core.mcp.tools.system import _status as system_status

    @server.resource("trace://system/status", name="Trace status", mime_type="application/json")
    def status() -> str:
        return _resource(ctx, "trace://system/status", lambda: system_status(ctx))

    @server.resource("trace://cases/{number}", name="Case dossier", mime_type="application/json")
    def case(number: str) -> str:
        return _resource(ctx, f"trace://cases/{number}", lambda: case_get(ctx, number))

    @server.resource("trace://cases/{number}/audit", name="Case audit events", mime_type="application/json")
    def case_audit(number: str) -> str:
        return _resource(
            ctx,
            f"trace://cases/{number}/audit",
            lambda: audit_list(ctx, number, None, None, None, None, None, None, "summary", 50, 0),
        )

    @server.resource("trace://audit/{seq}", name="Audit event", mime_type="application/json")
    def audit_event(seq: str) -> str:
        return _resource(ctx, f"trace://audit/{seq}", lambda: audit_get(ctx, int(seq)))

    @server.resource("trace://devices/{serial}/history", name="Device history", mime_type="application/json")
    def history(serial: str) -> str:
        return _resource(ctx, f"trace://devices/{serial}/history", lambda: device_history(ctx, serial, 50))

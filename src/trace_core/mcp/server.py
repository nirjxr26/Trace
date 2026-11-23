import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from mcp.server import MCPServer
from pydantic import ConfigDict

from trace_core import __version__
from trace_core.audit.builder import command_context
from trace_core.core.database.session import DatabaseSessionManager, db_manager
from trace_core.mcp import MCP_PROTOCOL_VERSION, SERVER_NAME
from trace_core.mcp.errors import failure, result
from trace_core.mcp.identity import active_operator


class ServerContext:
    def __init__(self, session_manager: DatabaseSessionManager, transport: str) -> None:
        self.session_manager = session_manager
        self.transport = transport
        self.version = __version__
        self.protocol_version = MCP_PROTOCOL_VERSION
        self.install_lock = threading.BoundedSemaphore(1)


def build_server(session_manager: DatabaseSessionManager | None = None, *, transport: str = "stdio") -> MCPServer:
    from trace_core.mcp.tools import register_all

    manager = session_manager or db_manager
    server = MCPServer(SERVER_NAME, version=__version__)
    ctx = ServerContext(manager, transport)
    register_all(server, ctx)
    return server


def mcp_tool(
    server: MCPServer, name: str, *, annotations: Any, description: str
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    decorator = server.tool(name=name, description=description, annotations=annotations)

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        wrapped = decorator(fn)
        tool = server._tool_manager.get_tool(name)
        assert tool is not None, f"tool {name} was not registered"
        base_model = tool.fn_metadata.arg_model
        strict_model = type(
            f"{name}StrictArguments",
            (base_model,),
            {"model_config": ConfigDict(extra="forbid", arbitrary_types_allowed=True)},
        )
        tool.fn_metadata.arg_model = strict_model
        tool.parameters["additionalProperties"] = False
        return wrapped

    return register


def execute(ctx: ServerContext, tool: str, operation: Callable[[], dict[str, Any]]) -> Any:
    correlation_id = uuid.uuid4().hex
    started = time.monotonic()
    operator = "unknown"
    outcome = "ok"
    error_code = ""
    logger = structlog.get_logger()
    try:
        with command_context(f"mcp {tool}"):
            operator_row = active_operator(ctx.session_manager)
            operator = f"{operator_row.name}@{operator_row.host}"
            payload = operation()
        return result(payload)
    except Exception as exc:
        outcome = "error"
        from trace_core.mcp.errors import map_error

        error_code = map_error(exc, correlation_id)["code"]
        logger.error(
            "mcp_tool_failure",
            tool=tool,
            correlation_id=correlation_id,
            error_code=error_code,
            error_type=type(exc).__name__,
        )
        return failure(exc, correlation_id)
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "mcp_tool_call",
            tool=tool,
            correlation_id=correlation_id,
            operator=operator,
            duration_ms=duration_ms,
            outcome=outcome,
            error_code=error_code,
        )

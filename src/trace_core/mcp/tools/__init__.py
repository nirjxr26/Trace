from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from trace_core.mcp.server import ServerContext

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
OPEN_WORLD_READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)


def register_all(server: MCPServer, ctx: ServerContext) -> None:
    from trace_core.mcp.tools import audit, cases, devices, system

    system.register(server, ctx)
    cases.register(server, ctx)
    audit.register(server, ctx)
    devices.register(server, ctx)

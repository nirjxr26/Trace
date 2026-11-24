from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from trace_core.core.database.session import sanitized_db_identity
from trace_core.mcp import services
from trace_core.mcp.constants import (
    TOOL_DB_MIGRATE,
    TOOL_RECOVERY,
    TOOL_STATUS,
    TOOL_UNINSTALL,
    TOOL_UPDATE_INSTALL,
)
from trace_core.mcp.identity import operator_summary
from trace_core.mcp.schemas import DbMigrateArgs, RecoveryArgs, UninstallArgs, UpdateInstallArgs, checked
from trace_core.mcp.serialize import to_result
from trace_core.mcp.server import ServerContext, execute, mcp_tool
from trace_core.mcp.tools import DESTRUCTIVE, READ_ONLY

Confirm = Annotated[str, Field(min_length=1, max_length=64)]
TargetVersion = Annotated[str, Field(min_length=1, max_length=64)]


def register(server: MCPServer, ctx: ServerContext) -> None:
    @mcp_tool(server, TOOL_STATUS, annotations=READ_ONLY, description="Report server, database, and operator status.")
    def trace_status() -> dict:
        return execute(ctx, TOOL_STATUS, lambda: _status(ctx))

    @mcp_tool(
        server,
        TOOL_UPDATE_INSTALL,
        annotations=DESTRUCTIVE,
        description="Install a signed release after confirming the exact target version. Admin only.",
    )
    def trace_update_install(target_version: TargetVersion, confirm: TargetVersion) -> dict:
        return execute(ctx, TOOL_UPDATE_INSTALL, lambda: _install(ctx, target_version, confirm))

    @mcp_tool(
        server,
        TOOL_RECOVERY,
        annotations=DESTRUCTIVE,
        description="Recover an interrupted update. Admin only. Confirm with RECOVER.",
    )
    def trace_recovery(confirm: Confirm) -> dict:
        return execute(ctx, TOOL_RECOVERY, lambda: _recover(ctx, confirm))

    @mcp_tool(
        server,
        TOOL_DB_MIGRATE,
        annotations=DESTRUCTIVE,
        description="Apply pending database migrations. Admin only. Confirm with MIGRATE.",
    )
    def trace_db_migrate(confirm: Confirm) -> dict:
        return execute(ctx, TOOL_DB_MIGRATE, lambda: _migrate(ctx, confirm))

    @mcp_tool(
        server,
        TOOL_UNINSTALL,
        annotations=DESTRUCTIVE,
        description="Uninstall Trace from a terminal, not from this live MCP connection.",
    )
    def trace_uninstall(confirm: Confirm) -> dict:
        return execute(ctx, TOOL_UNINSTALL, lambda: _uninstall(confirm))


def _status(ctx: ServerContext) -> dict:
    healthy, _ = ctx.session_manager.check_connection()
    return to_result(
        {
            "server_version": ctx.version,
            "protocol_version": ctx.protocol_version,
            "database": {"identity": sanitized_db_identity(ctx.session_manager._url), "healthy": healthy},
            "operator": operator_summary(ctx.session_manager),
            "transport": ctx.transport,
        }
    )


def _install(ctx: ServerContext, target_version: str, confirm: str) -> dict:
    checked(UpdateInstallArgs, {"target_version": target_version, "confirm": confirm})
    with ctx.install_lock:
        return to_result(services.install_update(ctx.session_manager, target_version))


def _recover(ctx: ServerContext, confirm: str) -> dict:
    checked(RecoveryArgs, {"confirm": confirm})
    with ctx.install_lock:
        return to_result(services.recover_installation(ctx.session_manager))


def _migrate(ctx: ServerContext, confirm: str) -> dict:
    checked(DbMigrateArgs, {"confirm": confirm})
    with ctx.install_lock:
        return to_result(services.migrate_database(ctx.session_manager))


def _uninstall(confirm: str) -> dict:
    checked(UninstallArgs, {"confirm": confirm})
    services.uninstall_refused()

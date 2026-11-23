import sys

import typer

from trace_core.core.cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.operators import bootstrap_current_operator

mcp_app = typer.Typer(name="mcp", help="Model Context Protocol server for Trace.")


@mcp_app.command("setup")
def setup() -> None:
    from trace_core.mcp import autoconfig

    result = autoconfig.setup()
    if result == ["disabled"]:
        typer.echo("Trace MCP is disabled via TRACE_MCP_DISABLED=1. Run with the var unset to enable.")
        raise typer.Exit(0)
    typer.echo(f"Trace MCP configured: {', '.join(result)}")


@mcp_app.command("disable")
def disable() -> None:
    from trace_core.mcp import autoconfig

    result = autoconfig.disable()
    typer.echo(f"Trace MCP disabled: {', '.join(result)}")
    typer.echo("Re-enable with: trace mcp setup")


_INSTALL_HINT = 'Trace MCP support is not installed. Install it with: pip install "trace[mcp]"'


@mcp_app.command("serve")
def serve() -> None:
    try:
        from trace_core.mcp.server import build_server
    except ImportError:
        typer.echo(_INSTALL_HINT, err=True)
        raise typer.Exit(EXIT_USAGE) from None

    manager = DatabaseSessionManager()
    healthy, message = manager.check_connection()
    if not healthy:
        typer.echo(f"Trace MCP server cannot start: {message}", err=True)
        raise typer.Exit(EXIT_ERROR)
    try:
        bootstrap_current_operator(manager)
    except Exception as exc:
        typer.echo(f"Trace MCP server cannot provision the current operator: {type(exc).__name__}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    try:
        build_server(manager, transport="stdio").run(transport="stdio")
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(f"Trace MCP server stopped: {type(exc).__name__}", file=sys.stderr)
        raise typer.Exit(EXIT_ERROR) from exc

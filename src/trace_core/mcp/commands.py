import sys

import typer

from trace_core.core.cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.operators import bootstrap_current_operator

mcp_app = typer.Typer(name="mcp", help="Model Context Protocol server for Trace.")

_HOST_LABELS = {
    "codex": "Codex",
    "claude-code": "Claude Code",
    "opencode": "OpenCode",
    "claude-desktop": "Claude Desktop",
    "cursor": "Cursor",
    "vscode-copilot": "VS Code (Copilot)",
    "windsurf": "Windsurf",
    "zed": "Zed",
    "zed-settings": "Zed settings",
}


def format_host_result(entries: list[str], heading: str, *, color: bool = False) -> str:
    lines = [heading, ""]
    for entry in entries:
        name, _, status = entry.rpartition(":")
        label = _HOST_LABELS.get(name, name)
        text = status.upper()
        if color and status == "ok":
            text = f"\033[32m{text}\033[0m"
        elif color and status == "removed":
            text = f"\033[31m{text}\033[0m"
        lines.append(f"    {label:<28} {text}")
    return "\n".join(lines)


@mcp_app.command("setup")
def setup() -> None:
    from trace_core.mcp import autoconfig

    try:
        result = autoconfig.setup(on_progress=typer.echo)
    except RuntimeError as exc:
        typer.echo("Trace MCP setup failed.", err=True)
        typer.echo(f"Reason: {exc}", err=True)
        raise typer.Exit(1) from None
    if result == ["disabled"]:
        typer.echo("Trace MCP is disabled via TRACE_MCP_DISABLED=1. Run with the var unset to enable.")
        raise typer.Exit(0)
    typer.echo("")
    typer.echo(format_host_result(result, "Trace MCP configured:", color=True))


@mcp_app.command("disable")
def disable() -> None:
    from trace_core.mcp import autoconfig

    result = autoconfig.disable(on_progress=typer.echo)
    typer.echo("")
    typer.echo(format_host_result(result, "Trace MCP removed:", color=True))
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

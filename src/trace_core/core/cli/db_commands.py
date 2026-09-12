"""Typer CLI commands for database management and migrations."""

import typer
from rich.table import Table

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.database.migrations import (
    apply_migrations,
    get_applied_migrations,
    get_pending_migrations,
    get_table_names,
)
from trace_core.core.database.session import db_manager
from trace_core.core.settings import settings
from trace_core.core.ui.renderers import console, create_key_value_grid, format_india_datetime

db_app = typer.Typer(name="db", help="Database health checks, schema initialization, and migrations.")


def _mask_db_url(url: str) -> str:
    """Mask password credentials in database URL for safe terminal rendering."""
    if "@" in url and "://" in url:
        prefix, rest = url.split("://", 1)
        credentials, host_db = rest.split("@", 1)
        if ":" in credentials:
            user, _ = credentials.split(":", 1)
            return f"{prefix}://{user}:*****@{host_db}"
        return f"{prefix}://*****@{host_db}"
    return url


def _require_db() -> None:
    """Abort command when the database is unreachable."""
    is_healthy, message = db_manager.check_connection()
    if not is_healthy:
        console.print(f"[bold red]Cannot connect to database:[/bold red] {message}")
        raise typer.Exit(code=1)


@db_app.command("status")
def db_status() -> None:
    """Check database connection and show migration / table status."""
    with capture_cli_errors("Database Health Check Failed"):
        is_healthy, message = db_manager.check_connection()
        masked_url = _mask_db_url(settings.database_url)

        status_text = f"[green]Online[/green] ({message})" if is_healthy else f"[red]Offline[/red] ({message})"
        grid = create_key_value_grid(
            [
                ("Database URL", masked_url),
                ("Connection", status_text),
            ],
            width=16,
        )
        console.print("")
        console.print("[bold cyan]Trace Database Status[/bold cyan]")
        console.print(grid)

        if not is_healthy:
            raise typer.Exit(code=1)

        # Inspect tables
        tables = get_table_names(db_manager.engine)
        applied = get_applied_migrations(db_manager.engine)
        pending = get_pending_migrations(db_manager.engine)

        console.print("\n[bold]Tables:[/bold] " + (", ".join(tables) if tables else "[dim]None[/dim]"))

        table = Table(title="Schema Migrations", box=None)
        table.add_column("Version", style="bold")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Applied At")

        for m in applied:
            table.add_row(
                str(m["version"]),
                m["name"],
                "[green]Applied[/green]",
                format_india_datetime(m["applied_at"]) if m["applied_at"] else "N/A",
            )
        for version, name in pending:
            table.add_row(
                str(version),
                name,
                "[yellow]Pending[/yellow]",
                "-",
            )

        if applied or pending:
            console.print(table)
        else:
            console.print("[dim]No migrations recorded.[/dim]")


@db_app.command("init")
def db_init() -> None:
    """Initialize database schema and apply initial migrations."""
    with capture_cli_errors("Database Initialization Failed"):
        _require_db()
        db_manager.init_schema()
        tables = get_table_names(db_manager.engine)
        console.print("[bold green][OK] Database schema initialized successfully![/bold green]")
        console.print(f"[dim]Existing tables: {', '.join(tables)}[/dim]")


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending schema migrations."""
    with capture_cli_errors("Database Migration Failed"):
        _require_db()
        applied = apply_migrations(db_manager.engine)
        if applied:
            console.print(f"[bold green][OK] Applied {len(applied)} migration(s):[/bold green]")
            for name in applied:
                console.print(f"  [green]✓[/green] {name}")
        else:
            console.print("[dim]Database is already up to date. No pending migrations.[/dim]")

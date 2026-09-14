"""Typer CLI commands for database management and migrations."""

import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.database.migrations import (
    apply_migrations,
    get_applied_migrations,
    get_pending_migrations,
    get_table_names,
)
from trace_core.core.database.session import db_manager, sanitized_db_url
from trace_core.core.settings import settings
from trace_core.core.ui.renderers import (
    breakpoint_width,
    console,
    create_key_value_grid,
    fit_text,
    kv_width,
    render_success,
    table_padding,
)

db_app = typer.Typer(name="db", help="Database health checks, schema initialization, and migrations.")


def _require_db() -> None:
    """Abort command when the database is unreachable."""
    from trace_core.core.ui.renderers import render_error_card

    is_healthy, message = db_manager.check_connection()
    if not is_healthy:
        render_error_card("Cannot Connect to Database", message, "Start PostgreSQL or set TRACE_DATABASE_URL.")
        raise typer.Exit(code=1)


@db_app.command("status")
def db_status() -> None:
    """Check database connection and show migration / table status."""
    with capture_cli_errors("Database Health Check Failed"):
        is_healthy, message = db_manager.check_connection()
        masked_url = sanitized_db_url(settings.database_url)

        status_text = f"[green]Online[/green] ({message})" if is_healthy else f"[red]Offline[/red] ({message})"
        bp, term_w = breakpoint_width()
        shown_url = fit_text(masked_url, max(20, term_w - 22)) if bp == "XS" else masked_url
        grid = create_key_value_grid(
            [
                ("Database URL", shown_url),
                ("Connection", status_text),
            ],
            width=kv_width(bp, narrow=12, default=16),
            padding=table_padding(bp),
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

        tables_str = ", ".join(tables) if tables else "None"
        if bp == "XS":
            tables_str = fit_text(tables_str, max(20, term_w - 12))
        console.print("\n[bold]Tables:[/bold] " + (tables_str if tables else "[dim]None[/dim]"))

        from rich.text import Text

        from trace_core.core.ui.renderers import format_india_table_time, render_minimalist_table

        if bp == "XS":
            columns: list[tuple[str, dict]] = [
                ("Ver", {"style": "bold", "no_wrap": True, "max_width": 5}),
                ("Name", {"overflow": "ellipsis", "max_width": max(16, term_w - 50)}),
            ]
        else:
            columns = [
                ("Ver", {"style": "bold", "no_wrap": True, "max_width": 5}),
                ("Name", {"overflow": "ellipsis", "max_width": max(16, term_w - 50)}),
                ("Status", {"no_wrap": True, "max_width": 10}),
                ("Applied", {"style": "dim", "no_wrap": True, "max_width": 14}),
            ]
        rows: list[list] = []
        for m in applied:
            row = [str(m["version"]), m["name"]]
            if bp != "XS":
                row += [
                    Text("Applied", style="green"),
                    format_india_table_time(m["applied_at"]) if m["applied_at"] else "N/A",
                ]
            rows.append(row)
        for version, name in pending:
            row = [str(version), name]
            if bp != "XS":
                row += [Text("Pending", style="yellow"), "-"]
            rows.append(row)
        render_minimalist_table("Schema Migrations", columns, rows, empty_message="No migrations recorded.")


@db_app.command("init")
def db_init() -> None:
    """Initialize database schema and apply initial migrations."""
    with capture_cli_errors("Database Initialization Failed"):
        _require_db()
        db_manager.init_schema()
        tables = get_table_names(db_manager.engine)
        render_success("Database schema initialized successfully!")
        console.print(f"[dim]Existing tables: {', '.join(tables)}[/dim]")


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending schema migrations."""
    with capture_cli_errors("Database Migration Failed"):
        _require_db()
        applied = apply_migrations(db_manager.engine)
        if applied:
            render_success(f"Applied {len(applied)} migration(s):")
            for name in applied:
                console.print(f"  [green]✓[/green] {name}")
        else:
            console.print("[dim]Database is already up to date. No pending migrations.[/dim]")

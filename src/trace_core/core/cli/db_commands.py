"""Typer CLI commands for database management and migrations."""

import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.database.health import fetch_db_snapshot, migration_entries
from trace_core.core.database.migrations import apply_migrations, get_table_names
from trace_core.core.database.session import db_manager
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

    snap = fetch_db_snapshot(db_manager)
    if not snap.healthy:
        render_error_card("Cannot Connect to Database", snap.message, "Start PostgreSQL or set TRACE_DATABASE_URL.")
        raise typer.Exit(code=1)


def _migration_table_columns(bp: str, term_w: int) -> list[tuple[str, dict]]:
    """Migration columns: XS keeps Ver/Name, wider adds Status/Applied."""
    columns: list[tuple[str, dict]] = [
        ("Ver", {"style": "bold", "no_wrap": True, "max_width": 5}),
        ("Name", {"overflow": "ellipsis", "max_width": max(16, term_w - 50)}),
    ]
    if bp != "XS":
        columns += [
            ("Status", {"no_wrap": True, "max_width": 10}),
            ("Applied", {"style": "dim", "no_wrap": True, "max_width": 14}),
        ]
    return columns


def _migration_table_rows(entries: list[tuple], bp: str) -> list[list]:
    """Migration rows from shared entries. XS keeps Ver/Name only."""
    from rich.text import Text

    from trace_core.core.ui.renderers import format_india_table_time

    rows: list[list] = []
    for version, name, status, applied_at in entries:
        row = [str(version), name]
        if bp != "XS":
            if status == "Applied":
                row += [
                    Text("Applied", style="green"),
                    format_india_table_time(applied_at) if applied_at else "N/A",
                ]
            else:
                row += [Text("Pending", style="yellow"), "-"]
        rows.append(row)
    return rows


@db_app.command("status")
def db_status() -> None:
    """Check database connection and show migration / table status."""
    with capture_cli_errors("Database Health Check Failed"):
        from rich.text import Text

        snap = fetch_db_snapshot(db_manager)
        is_healthy, message, masked_url = snap.healthy, snap.message, snap.masked_url

        # Text with spans, not a markup string: the grid coerces plain strings
        # to literal Text, which used to print raw "[red]...[/red]" brackets.
        status_text = Text()
        status_text.append("Online" if is_healthy else "Offline", style="green" if is_healthy else "red")
        status_text.append(f" ({message})", style="dim")
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
        tables, applied, pending = snap.tables, snap.applied, snap.pending

        tables_str = ", ".join(tables) if tables else "None"
        if bp == "XS":
            tables_str = fit_text(tables_str, max(20, term_w - 12))
        console.print("\n[bold]Tables:[/bold] " + (tables_str if tables else "[dim]None[/dim]"))

        from trace_core.core.ui.renderers import render_minimalist_table

        render_minimalist_table(
            "Schema Migrations",
            _migration_table_columns(bp, term_w),
            _migration_table_rows(migration_entries(applied, pending), bp),
            empty_message="No migrations recorded.",
        )


@db_app.command("init")
def db_init() -> None:
    """Initialize database schema and apply initial migrations."""
    with capture_cli_errors("Database Initialization Failed"):
        _require_db()
        db_manager.init_schema()
        tables = get_table_names(db_manager.engine)
        render_success("Database schema initialized.")
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
            console.print("[dim]Up to date. No pending migrations.[/dim]")

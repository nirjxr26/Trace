"""Database tab: health, tables, migrations. One-button migrate with progress."""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, DataTable, Static

from trace_core.core.database.migrations import (
    apply_migrations,
    get_applied_migrations,
    get_pending_migrations,
    get_table_names,
)
from trace_core.core.database.session import DatabaseSessionManager, db_manager
from trace_core.core.errors import ApplicationError
from trace_core.core.settings import settings


class DbView(Vertical):
    """Ops surface: health pill, tables, migration list. `m` applies pending."""

    BINDINGS = [
        Binding("m", "migrate", "Migrate"),
    ]

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager

    @property
    def _mgr(self) -> DatabaseSessionManager:
        return self._manager or db_manager

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll

        with VerticalScroll(id="database-scroll"):
            with Vertical(id="database-health", classes="card"):
                yield Static("Connection", classes="card-title")
                yield Static("", id="db-health")
            with Vertical(id="database-tables", classes="card"):
                yield Static("Tables", classes="card-title")
                yield Static("", id="db-tables")
            with Vertical(id="database-migrations", classes="card"):
                yield Static("Migrations", classes="card-title")
                yield DataTable(id="db-migrations", cursor_type="row")
                yield Button("Apply pending migrations (m)", id="db-migrate")

    def on_mount(self) -> None:
        table = self.query_one("#db-migrations", DataTable)
        table.add_column("Ver", width=5)
        table.add_column("Name")
        table.add_column("Status", width=10)
        self.refresh_data()

    def focus_default(self) -> None:
        """Focus the migrations table. Called by the shell when this tab activates."""
        self.query_one("#db-migrations", DataTable).focus()

    def refresh_data(self) -> None:
        """Reload health + tables + migrations. Called on mount and tab switch."""
        from trace_core.core.database.session import sanitized_db_url

        mgr = self._mgr
        try:
            healthy, message = mgr.check_connection()
        except Exception as exc:  # pragma: no cover - defensive, connection checked above pattern
            healthy, message = False, str(exc)
        status = Text()
        status.append("● ", style="#5FD18A" if healthy else "#D06A73")
        status.append("Online" if healthy else "Offline", style="bold")
        status.append(f"  {sanitized_db_url(settings.database_url)}", style="dim")
        if not healthy:
            status.append(f"\n{message}", style="dim")
        self.query_one("#db-health", Static).update(status)
        if not healthy:
            return
        try:
            tables = get_table_names(mgr.engine)
            applied = {m["version"]: m["name"] for m in get_applied_migrations(mgr.engine)}
            pending = get_pending_migrations(mgr.engine)
        except ApplicationError as exc:
            self.app.notify(str(exc), severity="error")
            return
        self.query_one("#db-tables", Static).update(Text(f"Tables  {', '.join(tables)}", style="dim"))
        table = self.query_one("#db-migrations", DataTable)
        table.clear()
        for version in sorted(set(applied) | {v for v, _ in pending}):
            if version in applied:
                table.add_row(str(version), applied[version], Text("Applied", style="#5FD18A"))
            else:
                name = next(n for v, n in pending if v == version)
                table.add_row(str(version), name, Text("Pending", style="#D8B56A"))

    def run_command(self, command: str) -> None:
        """Entry for the palette."""
        if command == "migrate":
            self.action_migrate()

    @on(Button.Pressed, "#db-migrate")
    def _migrate_pressed(self) -> None:
        self.action_migrate()

    def action_migrate(self) -> None:
        try:
            applied = apply_migrations(self._mgr.engine)
        except (ApplicationError, RuntimeError) as exc:
            self.app.notify(str(exc), severity="error")
            return
        if applied:
            self.app.notify(f"Applied {len(applied)} migration(s).")
        else:
            self.app.notify("Already up to date.")
        self.refresh_data()

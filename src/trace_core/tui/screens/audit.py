"""Audit tab: live ledger stream + detail + scope + raw drawer."""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Input, Static

from trace_core.audit.dto import AuditEventDto, AuditFilterDto
from trace_core.audit.events import parse_details
from trace_core.audit.renderers import action_title
from trace_core.audit.service import AuditService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import format_india_datetime, sanitize_terminal
from trace_core.core.ui.theme import THEME_TOKENS
from trace_core.tui.actions import confirm_overwrite, run_guarded
from trace_core.tui.forms import RawModal, TextInputModal
from trace_core.tui.widgets import DossierScroll

TABLE_ID = "audit-table"


class AuditView(Vertical):
    """Top: stream table. Bottom: selected event detail. Filters on top."""

    BINDINGS = [
        Binding("s", "scope", "Scope case"),
        Binding("slash", "search", "Search"),
        Binding("v", "raw", "Raw"),
        Binding("e", "export", "Export"),
    ]

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._scope: str | None = None
        self._events: list[AuditEventDto] = []
        self._search_timer: Timer | None = None

    @property
    def _svc(self) -> AuditService:
        return AuditService(self._manager)

    def compose(self) -> ComposeResult:
        from trace_core.tui.widgets import DossierScroll

        with Horizontal(id="audit-main"):
            with Vertical(id="audit-left"):
                yield Input(placeholder="search actor / action / case…", id="audit-search")
                yield Static("", id="audit-scope")
                yield DataTable(id=TABLE_ID, cursor_type="row")
            with DossierScroll(id="audit-right"):
                yield Static("Select an event…", id="audit-detail")

    def on_mount(self) -> None:
        table = self.query_one(f"#{TABLE_ID}", DataTable)
        table.add_column("Seq", width=6)
        table.add_column("Event")
        self.refresh_data()

    def focus_default(self) -> None:
        """Focus the table. Called by the shell when this tab activates."""
        self.query_one(f"#{TABLE_ID}", DataTable).focus()

    def refresh_data(self) -> None:
        """Reload stream + detail. Called on mount, tab switch, and scope change."""
        query = self.query_one("#audit-search", Input).value.strip() or None
        scope = self._scope
        scope_widget = self.query_one("#audit-scope", Static)
        scope_widget.update(f"Scoped: {scope}   (s clears)" if scope else "")
        scope_widget.display = bool(scope)
        try:
            self._events = self._svc.list_events(AuditFilterDto(case_number=scope, search=query, limit=100))
        except Exception as exc:  # boundary: every service failure becomes a toast, never a crash
            self.app.notify(str(exc), severity="error")
            return
        from trace_core.audit.renderers import short_action_label

        table = self.query_one(f"#{TABLE_ID}", DataTable)
        table.clear()
        for e in self._events:
            table.add_row(str(e.seq), short_action_label(e.action), key=str(e.seq))
        self._render_detail()

    def _selected(self) -> AuditEventDto | None:
        table = self.query_one(f"#{TABLE_ID}", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self._events):
            return None
        return self._events[table.cursor_row]

    def _render_detail(self) -> None:
        from trace_core.audit.verifier import verify_event

        e = self._selected()
        if e is None:
            self.query_one("#audit-detail", Static).update(Text("No events.", style="dim"))
            return
        details = parse_details(e.payload_json)
        intact = verify_event(
            e.payload_json,
            e.payload_hash,
            e.prev_chain,
            e.chain_hash,
            e.seq,
            signature=e.signature,
            key_id=e.key_id,
        )
        pane = self.query_one("#audit-right", DossierScroll)
        rule = pane.divider()
        body = Text()
        body.append(f"#{e.seq}  {action_title(e.action.value)}\n", style=THEME_TOKENS["accent"])
        body.append(f"{sanitize_terminal(e.subject_case_number)} · {format_india_datetime(e.ts)}\n", style="dim")
        body.append("\n")
        body.append(rule)
        body.append("\n")
        body.append("Actor   ", style="dim")
        body.append(f"{sanitize_terminal(e.actor)} @ {sanitize_terminal(details.get('host', '-'))}\n")
        body.append("When    ", style="dim")
        body.append(f"{format_india_datetime(e.ts)}\n")
        body.append("\n")
        body.append(rule)
        body.append("\n")
        body.append("Event   ", style="dim")
        body.append(f"{e.action.value}\n")
        reason = (details.get("reason") or "").strip()
        if reason:
            body.append("Reason  ", style="dim")
            body.append(f"{sanitize_terminal(reason)}\n")
        changed = details.get("changed", [])
        body.append("\n")
        body.append(rule)
        body.append("\n")
        if changed:
            from trace_core.audit.renderers import format_change_value

            before, after = details.get("before", {}), details.get("after", {})
            body.append(f"\nCHANGES · {len(changed)}\n", style=THEME_TOKENS["accent"])
            body.append("\n")
            for field in changed:
                body.append(f"{field}\n", style="dim")
                body.append(f"  {sanitize_terminal(format_change_value(before.get(field)))}", style="#D06A73")
                body.append("  →  ")
                body.append(f"{sanitize_terminal(format_change_value(after.get(field)))}\n", style="#5FD18A")
            body.append("\n")
            body.append(rule)
        body.append("\nINTEGRITY · ", style=THEME_TOKENS["accent"])
        body.append("✓ VERIFIED\n" if intact else "✗ MISMATCH — run Verify\n", style="#5FD18A" if intact else "#D06A73")
        body.append("\n")
        body.append(f"Payload   {e.payload_hash}\n", style="dim")
        body.append(f"Previous  {e.prev_chain}\n", style="dim")
        body.append(f"Chain     {e.chain_hash}\n", style="dim")
        self.query_one("#audit-detail", Static).update(body)

    def run_command(self, command: str) -> None:
        """Entry for the palette."""
        if command == "export":
            self.action_export()
        elif command == "anchor":
            self.app.notify("Open the Integrity tab to check an anchor file.")
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

    @on(DataTable.RowHighlighted)
    def _highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == TABLE_ID:
            self._render_detail()

    @on(DataTable.RowSelected)
    def _opened(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == TABLE_ID:
            self.query_one("#audit-right").focus()

    @on(Input.Changed)
    def _searched(self, event: Input.Changed) -> None:
        if event.input.id == "audit-search":
            # Debounce keystrokes into one refresh; timers only delay, never drop.
            if self._search_timer is not None:
                self._search_timer.stop()
            self._search_timer = self.set_timer(0.25, self.refresh_data)

    def action_search(self) -> None:
        self.query_one("#audit-search", Input).focus()

    def action_scope(self) -> None:
        self.app.push_screen(TextInputModal("Scope to case (blank clears)", "2026-CR-0001"), self._scoped)

    def _scoped(self, value: str | None) -> None:
        self._scope = value
        self.refresh_data()

    def action_raw(self) -> None:
        e = self._selected()
        if e is None:
            self.app.notify("Select an event first.", severity="warning")
            return
        self.app.push_screen(RawModal(f"seq {e.seq} payload", e.payload_json))

    def action_export(self) -> None:
        self.app.push_screen(TextInputModal("Export bundle to", "bundle.jsonl"), self._exported)

    def _exported(self, path: str | None) -> None:
        if not path:
            return
        confirm_overwrite(self, path, lambda: self._do_export(path))

    def _do_export(self, path: str) -> None:
        def _export() -> str:
            out = self._svc.export(path)
            return f"Exported to {out}."

        run_guarded(self, _export)

"""Audit tab: live ledger stream + detail + scope + raw drawer."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Rule, Static

from trace_core.audit.dto import AuditEventDto, AuditFilterDto
from trace_core.audit.events import parse_details
from trace_core.audit.renderers import action_title, subject_case_label
from trace_core.audit.service import AuditService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import format_india_datetime, sanitize_terminal
from trace_core.core.ui.theme import THEME_TOKENS
from trace_core.tui.actions import confirm_overwrite, run_guarded
from trace_core.tui.forms import RawModal, TextInputModal
from trace_core.tui.widgets import DossierScroll, TablePane

TABLE_ID = "audit-table"
AUDIT_HEADER_ID = "audit-header"
AUDIT_DETAIL_ID = "audit-detail"
TABLE_COLUMNS = (("Seq", 7), ("Event", 12))


class AuditView(TablePane[AuditEventDto]):
    """Top: stream table. Bottom: selected event detail. Filters on top."""

    BINDINGS = [
        Binding("s", "scope", "Scope case"),
        Binding("slash", "search", "Search"),
        Binding("v", "raw", "Raw"),
        Binding("e", "export", "Export"),
    ]

    TABLE_ID = TABLE_ID
    HEADER_ID = AUDIT_HEADER_ID
    DETAIL_ID = "audit-right"
    SEARCH_ID = "audit-search"
    COLUMNS = TABLE_COLUMNS

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._scope: str | None = None
        self._events: list[AuditEventDto] = []

    @property
    def _svc(self) -> AuditService:
        return AuditService(self._manager)

    def compose(self) -> ComposeResult:
        from trace_core.tui.widgets import DossierScroll

        with Horizontal(id="audit-main"):
            with Vertical(id="audit-left"):
                yield Input(placeholder="Search actor, action, case, seq...", id="audit-search")
                yield Static("", id="audit-scope")
                yield Rule()
                yield Static("", id=AUDIT_HEADER_ID, classes="table-head")
                yield Rule()
                yield DataTable(id=TABLE_ID, cursor_type="row", show_header=False)
            with DossierScroll(id="audit-right"):
                yield Static("Select an event…", id=AUDIT_DETAIL_ID)

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
        self.fill_table(self._events, [str(e.seq) for e in self._events])

    def row_cells(self, event: AuditEventDto, selected: bool) -> list:  # type: ignore[no-untyped-def]
        from trace_core.audit.renderers import short_action_label
        from trace_core.tui.theme import SELECT_PREFIX

        prefix = SELECT_PREFIX if selected else "  "
        return [f"{prefix}{event.seq}", short_action_label(event.action)]

    def render_detail(self) -> None:
        from trace_core.audit.verifier import verify_event
        from trace_core.tui.theme import DOT_BAD, DOT_OK, integrity_line

        e = self._selected()
        if e is None:
            from trace_core.tui.theme import detail_placeholder

            self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._events), "No audit events found — create or close a case.")
            )
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
        body.append(rule)
        body.append("\n")
        body.append("Case    ", style="dim")
        body.append(f"{sanitize_terminal(subject_case_label(e.subject_case_number))}\n")
        body.append("Actor   ", style="dim")
        body.append(f"{sanitize_terminal(e.actor)}\n")
        body.append("When    ", style="dim")
        body.append(f"{format_india_datetime(e.ts)}\n")
        body.append("Event   ", style="dim")
        body.append(f"{e.action.value}\n")
        reason = (details.get("reason") or "").strip()
        if reason:
            body.append("Reason  ", style="dim")
            body.append(f"{sanitize_terminal(reason)}\n")
        changed = details.get("changed", [])
        if changed:
            from trace_core.audit.renderers import format_change_value

            before, after = details.get("before", {}), details.get("after", {})
            body.append(rule)
            body.append(f"\nCHANGES · {len(changed)}\n", style=THEME_TOKENS["accent"])
            for field in changed:
                body.append(f"{field}\n", style="dim")
                body.append(f"  {sanitize_terminal(format_change_value(before.get(field)))}", style=DOT_BAD)
                body.append("  →  ")
                body.append(f"{sanitize_terminal(format_change_value(after.get(field)))}\n", style=DOT_OK)
        body.append(rule)
        body.append("\nINTEGRITY\n", style=THEME_TOKENS["accent"])
        body.append_text(integrity_line(intact))
        body.append("\n")
        self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(body)

    def run_command(self, command: str) -> None:
        """Entry for the palette."""
        action = command.removeprefix("audit-")
        if action == "export":
            self.action_export()
        elif action == "anchor":
            self.app.notify("Open the Integrity tab to check an anchor file.")
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

    def action_scope(self) -> None:
        self.app.push_screen(TextInputModal("Scope to case (blank clears)", "2026-CR-0001"), self._scoped)

    def _scoped(self, value: str | None) -> None:
        self._scope = value
        self.refresh_data()

    def action_raw(self) -> None:
        e = self._selected()
        if e is None:
            from trace_core.tui.theme import detail_placeholder

            self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._events), "No audit events found — create or close a case.")
            )
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

"""Cases tab: live table + dossier + raw drawer + mutation forms."""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Input, Rule, Static

from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto, CaseFilterDto, CaseResponseDto, CaseUpdateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import ApplicationError
from trace_core.core.ui.renderers import format_india_datetime, sanitize_terminal
from trace_core.tui.actions import run_guarded
from trace_core.tui.forms import CaseForm, RawModal, TextInputModal, TypedConfirmModal, YesNoModal
from trace_core.tui.theme import STATUS_COLORS, THEME_TOKENS, status_text, table_head_text
from trace_core.tui.widgets import DossierScroll

TABLE_ID = "case-table"
CASE_HEADER_ID = "case-header"
TABLE_COLUMNS = (("Case #", 16), ("Status", 10))
_NO_SELECTION = "Select a case first."
_TITLE_STYLE = "bold #E5EAF0"


class CasesView(Vertical):
    """Left: filterable table. Right: dossier of the highlighted row."""

    BINDINGS = [
        Binding("c", "create", "Create"),
        Binding("e", "edit", "Edit"),
        Binding("x", "seal", "Seal"),
        Binding("a", "archive", "Archive"),
        Binding("p", "purge", "Purge"),
        Binding("u", "restore", "Restore"),
        Binding("r", "recent", "Recent"),
        Binding("slash", "search", "Search"),
        Binding("v", "raw", "Raw"),
    ]

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._recent = False
        self._cases: list[CaseResponseDto] = []
        self._event_cache: dict[str, list] = {}
        self._search_timer: Timer | None = None
        self._last_cursor: int | None = None

    @property
    def _cases_svc(self) -> CaseService:
        return CaseService(self._manager)

    def compose(self) -> ComposeResult:
        with Horizontal(id="cases-top"):
            with Vertical(id="cases-left"):
                yield Input(placeholder="Search cases...", id="case-search")
                yield Rule()
                yield Static("", id=CASE_HEADER_ID, classes="table-head")
                yield Rule()
                yield DataTable(id=TABLE_ID, cursor_type="row", show_header=False)
            with DossierScroll(id="cases-right"):
                yield Static("Select a case…", id="case-dossier")

    def on_mount(self) -> None:
        from trace_core.tui.widgets import mount_header_table

        mount_header_table(self, TABLE_ID, CASE_HEADER_ID, TABLE_COLUMNS)
        self.refresh_data()

    def focus_default(self) -> None:
        """Focus the table. Called by the shell when this tab activates."""
        self.query_one(f"#{TABLE_ID}", DataTable).focus()

    def _query(self) -> list[CaseResponseDto]:
        query = self.query_one("#case-search", Input).value.strip() or None
        return self._cases_svc.list_cases(
            CaseFilterDto(search=query, include_deleted=True, limit=100, recent=self._recent)
        )

    def refresh_data(self) -> None:
        """Reload table + dossier. Called on mount, tab switch, and after every mutation."""
        self._event_cache.clear()
        try:
            self._cases = self._query()
        except Exception as exc:  # boundary: every service failure becomes a toast, never a crash
            self.app.notify(str(exc), severity="error")
            return
        table = self.query_one(f"#{TABLE_ID}", DataTable)
        table.clear()
        cursor = table.cursor_row if table.cursor_row is not None else 0
        for idx, case in enumerate(self._cases):
            table.add_row(*self._row_cells(case, idx == cursor), key=case.number)
        try:
            if self._cases:
                table.move_cursor(row=min(cursor, len(self._cases) - 1))
        except Exception:
            pass
        self._last_cursor = table.cursor_row if table.cursor_row is not None else 0
        self.query_one(f"#{CASE_HEADER_ID}", Static).update(
            f"{table_head_text(list(TABLE_COLUMNS))}  · {len(self._cases)}"
        )
        self._render_dossier()

    def _row_cells(self, case: CaseResponseDto, selected: bool) -> list:  # type: ignore[no-untyped-def]
        from trace_core.core.ui.renderers import sanitize_terminal
        from trace_core.tui.theme import SELECT_PREFIX

        first = f"{SELECT_PREFIX}{case.number}" if selected else f"  {case.number}"
        return [sanitize_terminal(first), status_text(case.status, case.is_deleted)]

    def _repaint_selection(self) -> None:
        from trace_core.tui.widgets import repaint_selection

        table = self.query_one(f"#{TABLE_ID}", DataTable)
        if not self._cases:
            return
        cursor = table.cursor_row if table.cursor_row is not None else 0
        repaint_selection(table, self._last_cursor, cursor, lambda idx, sel: self._row_cells(self._cases[idx], sel))
        self._last_cursor = cursor

    def _selected(self) -> CaseResponseDto | None:
        from trace_core.tui.widgets import selected_item

        return selected_item(self.query_one(f"#{TABLE_ID}", DataTable), self._cases)

    def _render_dossier(self) -> None:
        from trace_core.tui.widgets import DossierScroll

        case = self._selected()
        if case is None:
            if not self._cases:
                self.query_one("#case-dossier", Static).update(Text("No cases found — press c to create.", style="dim"))
            else:
                self.query_one("#case-dossier", Static).update(Text("Select a case…", style="dim"))
            return
        events = self._dossier_events(case)
        rule = self.query_one("#cases-right", DossierScroll).divider()
        status_label = "ARCHIVED" if case.is_deleted else str(getattr(case.status, "value", case.status))
        status_color = STATUS_COLORS.get("ARCHIVED" if case.is_deleted else status_label, "#E5EAF0")

        body = Text()
        self._append_head(body, case, rule, status_label, status_color)
        self._append_meta(body, case, rule)
        self._append_integrity(body, events, rule)
        self._append_history(body, case, events)
        self.query_one("#case-dossier", Static).update(body)

    def _append_integrity(self, body, events, rule) -> None:  # type: ignore[no-untyped-def]
        from trace_core.audit.verifier import verify_event
        from trace_core.tui.theme import integrity_line

        verified = True
        for e in events:
            try:
                if not verify_event(
                    e.payload_json,
                    e.payload_hash,
                    e.prev_chain,
                    e.chain_hash,
                    e.seq,
                    signature=e.signature,
                    key_id=e.key_id,
                ):
                    verified = False
                    break
            except Exception:
                verified = False
                break
        body.append(rule)
        body.append("\nINTEGRITY\n", style=THEME_TOKENS["accent"])
        body.append_text(integrity_line(verified))
        body.append("\n")
        body.append(rule)
        body.append("\n")

    def _append_head(self, body, case, rule, status_label, status_color) -> None:  # type: ignore[no-untyped-def]
        # Identity + status + examiner. Panel padding is 1; one blank line per section.
        body.append(f"{sanitize_terminal(case.number)}\n", style="#72B7D3")
        body.append(f"{sanitize_terminal(case.title or 'Untitled')}\n", style=_TITLE_STYLE)
        body.append("\u25cf ", style=status_color)
        body.append(f"{status_label}\n", style=f"bold {status_color}")
        body.append(rule)
        body.append("\n")
        body.append(f"{'Lead Examiner':<15} ", style="dim")
        body.append(f"{sanitize_terminal(case.lead_examiner or '\u2014')}\n", style="#E5EAF0")
        body.append(f"{'Tags':<15} ", style="dim")
        if case.tags:
            body.append(sanitize_terminal(" ".join(f"#{t}" for t in case.tags)) + "\n", style="#6FA8B8")
        else:
            body.append("\u2014\n", style="dim")

    def _append_meta(self, body, case, rule) -> None:  # type: ignore[no-untyped-def]
        # Timestamp/closure rows plus DESCRIPTION/NOTES sections.
        body.append(rule)
        body.append("\n")
        body.append(f"{'Opened':<15} ", style="dim")
        body.append(f"{format_india_datetime(case.opened_at)}\n")
        body.append(f"{'Updated':<15} ", style="dim")
        body.append(f"{format_india_datetime(case.updated_at)}\n")
        body.append(f"{'Closed':<15} ", style="dim")
        if case.closed_at:
            body.append(f"{format_india_datetime(case.closed_at)}\n")
            if case.closure_reason:
                body.append(f"{'Reason':<15} ", style="dim")
                body.append(f"{sanitize_terminal(case.closure_reason)}\n")
        else:
            body.append("—\n", style="dim")
        if case.description:
            body.append(rule)
            body.append("\nDESCRIPTION\n", style=THEME_TOKENS["accent"])
            body.append(f"  {sanitize_terminal(case.description)}\n")
        if case.notes:
            body.append(rule)
            body.append("\nNOTES\n", style=THEME_TOKENS["accent"])
            body.append(f"  {sanitize_terminal(case.notes)}\n")

    def _dossier_events(self, case):  # type: ignore[no-untyped-def]
        # Recent audit events for the dossier, cached per case. Cleared on refresh.
        # Empty on ledger errors.
        if case.number not in self._event_cache:
            try:
                self._event_cache[case.number] = AuditService(self._manager).list_events(
                    AuditFilterDto(case_number=case.number, limit=6)
                )
            except ApplicationError:
                return []
        return self._event_cache[case.number]

    def _append_history(self, body, case, events) -> None:  # type: ignore[no-untyped-def]
        # HISTORY proof block shared by dossier renders.
        if not events:
            return
        from trace_core.audit.renderers import short_action_label
        from trace_core.core.ui.renderers import format_ledger_time

        count = f"{len(events)} event" + ("s" if len(events) != 1 else "")
        body.append(f"HISTORY \u00b7 {count}\n", style=THEME_TOKENS["accent"])
        for e in events[:5]:
            body.append(f"{format_ledger_time(e.ts)}  ", style="dim")
            body.append(f"{short_action_label(e.action)}", style=_TITLE_STYLE)
            body.append(f"  \u00b7  {sanitize_terminal(e.actor)}\n", style="dim")

    def run_command(self, command: str) -> None:
        """Entry for the palette. Unknown ids toast instead of vanishing."""
        action = getattr(self, f"action_{command.replace('case-', '')}", None)
        if callable(action) and getattr(action, "__name__", "").startswith("action_"):
            action()
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

    @on(DataTable.RowHighlighted)
    def _highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == TABLE_ID:
            self._repaint_selection()
            self._render_dossier()

    @on(DataTable.RowSelected)
    def _opened(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == TABLE_ID:
            self.query_one("#cases-right").focus()

    @on(Input.Changed)
    def _searched(self, event: Input.Changed) -> None:
        if event.input.id == "case-search":
            # Debounce keystrokes into one refresh; timers only delay, never drop.
            if self._search_timer is not None:
                self._search_timer.stop()
            self._search_timer = self.set_timer(0.25, self.refresh_data)

    def action_search(self) -> None:
        self.query_one("#case-search", Input).focus()

    def action_recent(self) -> None:
        self._recent = not self._recent
        self.app.notify("Recent first on." if self._recent else "Recent first off.")
        self.refresh_data()

    def action_raw(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify(_NO_SELECTION, severity="warning")
            return
        self.app.push_screen(RawModal(f"case show {case.number} --output json", case.model_dump_json(indent=2)))

    def action_create(self) -> None:
        self.app.push_screen(CaseForm("Create Case"), self._created)

    def _created(self, values: dict[str, str] | None) -> None:
        if not values:
            return
        from trace_core.cases.dto import parse_tags

        def _create() -> str:
            created = self._cases_svc.create_case(
                CaseCreateDto(
                    title=values["title"],
                    lead_examiner=values["examiner"],
                    number=values["number"] or None,
                    description=values["description"] or None,
                    notes=values["notes"] or None,
                    tags=parse_tags(values["tags"]) or [],
                ),
                actor=values["examiner"],
            )
            return f"Case {created.number} created."

        run_guarded(self, _create)

    def action_edit(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify(_NO_SELECTION, severity="warning")
            return
        initial = {
            "title": case.title,
            "examiner": case.lead_examiner,
            "description": case.description or "",
            "notes": case.notes or "",
            "tags": ", ".join(case.tags),
            "reason": "",
        }
        self.app.push_screen(CaseForm(f"Edit {case.number}", initial, for_create=False), self._edited)

    def _edited(self, values: dict[str, str] | None) -> None:
        case = self._selected()
        if not values or case is None:
            return
        from trace_core.cases.dto import parse_tags

        def _edit() -> str:
            self._cases_svc.update_case(
                case.number,
                CaseUpdateDto(
                    title=values["title"] or None,
                    lead_examiner=values["examiner"] or None,
                    description=values["description"] or None,
                    notes=values["notes"] or None,
                    tags=parse_tags(values["tags"]),
                ),
                reason=values["reason"],
            )
            return f"Case {case.number} updated."

        run_guarded(self, _edit)

    def action_seal(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify(_NO_SELECTION, severity="warning")
            return
        self.app.push_screen(
            TextInputModal("Reason for sealing", "why is this case closed?", required=True),
            lambda reason: self._seal_reason(case.number, reason),
        )

    def _seal_reason(self, number: str, reason: str | None) -> None:
        if not reason:
            return
        self.app.push_screen(
            TypedConfirmModal(f"Seal case {number} permanently?", number),
            lambda ok: self._sealed(number, reason) if ok else None,
        )

    def _sealed(self, number: str, reason: str = "") -> None:
        from trace_core.audit.anchor import latest_intent_status

        def _seal() -> str:
            self._cases_svc.close_case(number, reason=reason, actor=None)
            with self._cases_svc.session_manager.session() as session:
                state = latest_intent_status(session, number)
            return f"Case {number} sealed. Anchor: {state or 'UNKNOWN'}."

        run_guarded(self, _seal)

    def action_archive(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify(_NO_SELECTION, severity="warning")
            return
        self.app.push_screen(
            YesNoModal(f"Archive case {case.number}?"), lambda ok: self._archived(case.number) if ok else None
        )

    def _archived(self, number: str) -> None:
        def _apply() -> str:
            self._cases_svc.delete_case(number)
            return f"Case {number} archived."

        run_guarded(self, _apply)

    def action_purge(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify(_NO_SELECTION, severity="warning")
            return
        self.app.push_screen(
            TypedConfirmModal(f"PURGE case {case.number}? Irreversible.", case.number),
            lambda ok: self._purged(case.number) if ok else None,
        )

    def _purged(self, number: str) -> None:
        def _apply() -> str:
            self._cases_svc.delete_case(number, purge=True)
            return f"Case {number} purged."

        run_guarded(self, _apply)

    def action_restore(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify(_NO_SELECTION, severity="warning")
            return
        self.app.push_screen(
            YesNoModal(f"Restore archived case {case.number}?"),
            lambda ok: self._restored(case.number) if ok else None,
        )

    def _restored(self, number: str) -> None:
        def _apply() -> str:
            self._cases_svc.restore_case(number)
            return f"Case {number} restored."

        run_guarded(self, _apply)

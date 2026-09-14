"""Cases tab: live table + dossier + raw drawer + mutation forms."""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Static

from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto, CaseFilterDto, CaseResponseDto, CaseUpdateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import ApplicationError
from trace_core.core.ui.renderers import format_india_datetime
from trace_core.tui.forms import CaseForm, RawModal, TypedConfirmModal, YesNoModal
from trace_core.tui.theme import STATUS_COLORS
from trace_core.tui.widgets import DossierScroll


def _status_text(status: object, is_deleted: bool) -> Text:

    label = "ARCHIVED" if is_deleted else str(getattr(status, "value", status))
    color = STATUS_COLORS.get("ARCHIVED" if is_deleted else label, "#E5EAF0")
    if label == "UNDER_REVIEW":
        label = "REVIEW"
    return Text(label, style=color)


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

    @property
    def _cases_svc(self) -> CaseService:
        return CaseService(self._manager)

    def compose(self) -> ComposeResult:
        with Horizontal(id="cases-top"):
            with Vertical(id="cases-left"):
                yield Input(placeholder="search cases…", id="case-search")
                yield DataTable(id="case-table", cursor_type="row")
            with DossierScroll(id="cases-right"):
                yield Static("Select a case…", id="case-dossier")

    def on_mount(self) -> None:
        table = self.query_one("#case-table", DataTable)
        table.add_column("Case #", width=16)
        table.add_column("Status", width=10)
        self.refresh_data()

    def focus_default(self) -> None:
        """Focus the table. Called by the shell when this tab activates."""
        self.query_one("#case-table", DataTable).focus()

    def _query(self) -> list[CaseResponseDto]:
        query = self.query_one("#case-search", Input).value.strip() or None
        return self._cases_svc.list_cases(
            CaseFilterDto(search=query, include_deleted=True, limit=100, recent=self._recent)
        )

    def refresh_data(self) -> None:
        """Reload table + dossier. Called on mount, tab switch, and after every mutation."""
        try:
            self._cases = self._query()
        except ApplicationError as exc:
            self.app.notify(str(exc), severity="error")
            return
        table = self.query_one("#case-table", DataTable)
        table.clear()
        for case in self._cases:
            table.add_row(
                case.number,
                _status_text(case.status, case.is_deleted),
                key=case.number,
            )
        self._render_dossier()

    def _selected(self) -> CaseResponseDto | None:
        table = self.query_one("#case-table", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self._cases):
            return None
        return self._cases[table.cursor_row]

    def _render_dossier(self) -> None:
        from trace_core.tui.widgets import DossierScroll

        case = self._selected()
        if case is None:
            self.query_one("#case-dossier", Static).update(Text("No cases.", style="dim"))
            return
        try:
            events = AuditService(self._manager).list_events(AuditFilterDto(case_number=case.number, limit=6))
        except ApplicationError:
            events = []
        rule = self.query_one("#cases-right", DossierScroll).divider()
        status_label = "ARCHIVED" if case.is_deleted else str(getattr(case.status, "value", case.status))
        status_color = STATUS_COLORS.get("ARCHIVED" if case.is_deleted else status_label, "#E5EAF0")

        body = Text()
        body.append(f"{case.number}\n", style="#72B7D3")
        body.append(f"{case.title or 'Untitled'}\n", style="bold #E5EAF0")
        body.append("● ", style=status_color)
        body.append(f"{status_label} ", style=f"bold {status_color}")
        body.append(f"· Opened {format_india_datetime(case.opened_at)}\n", style="dim")
        body.append("\n")
        body.append(rule)
        body.append("\n")
        body.append(f"{'Lead Examiner':<15} ", style="dim")
        body.append(f"{case.lead_examiner or '—'}\n", style="#E5EAF0")
        body.append(f"{'Tags':<15} ", style="dim")
        if case.tags:
            body.append(" ".join(f"#{t}" for t in case.tags) + "\n", style="#6FA8B8")
        else:
            body.append("—\n", style="dim")
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
                body.append(f"{case.closure_reason}\n")
        else:
            body.append("— (active)\n", style="dim")
        body.append("\n")
        body.append(rule)
        if case.description:
            body.append("\nDESCRIPTION\n", style="bold #72B7D3")
            body.append(f"  {case.description}\n")
            body.append("\n")
            body.append(rule)
        if case.notes:
            body.append("\nNOTES\n", style="bold #72B7D3")
            body.append(f"  {case.notes}\n")
            body.append("\n")
            body.append(rule)
        if events:
            from trace_core.audit.renderers import short_action_label
            from trace_core.core.ui.renderers import format_ledger_time

            count = f"{len(events)} event" + ("s" if len(events) != 1 else "")
            body.append(f"\nHISTORY · {count}\n", style="bold #72B7D3")
            body.append("\n")
            for e in events[:5]:
                body.append(f"{format_ledger_time(e.ts)}  ", style="dim")
                body.append(f"{short_action_label(e.action)}", style="bold #E5EAF0")
                body.append(f"  ·  {e.actor}\n", style="dim")
        self.query_one("#case-dossier", Static).update(body)

    def run_command(self, command: str) -> None:
        """Entry for the palette. Unknown ids are ignored."""
        action = getattr(self, f"action_{command.replace('case-', '')}", None)
        if callable(action):
            action()

    @on(DataTable.RowHighlighted)
    def _highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "case-table":
            self._render_dossier()

    @on(DataTable.RowSelected)
    def _opened(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "case-table":
            self.query_one("#cases-right").focus()

    @on(Input.Changed)
    def _searched(self, event: Input.Changed) -> None:
        if event.input.id == "case-search":
            self.refresh_data()

    def action_search(self) -> None:
        self.query_one("#case-search", Input).focus()

    def action_recent(self) -> None:
        self._recent = not self._recent
        self.app.notify("Recent first on." if self._recent else "Recent first off.")
        self.refresh_data()

    def action_raw(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify("Select a case first.", severity="warning")
            return
        self.app.push_screen(RawModal(f"case show {case.number} --output json", case.model_dump_json(indent=2)))

    def action_create(self) -> None:
        self.app.push_screen(CaseForm("Create Case"), self._created)

    def _created(self, values: dict[str, str] | None) -> None:
        if not values:
            return
        from trace_core.cases.dto import parse_tags

        try:
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
            self.app.notify(f"Case {created.number} created.")
        except ApplicationError as exc:
            self.app.notify(str(exc), severity="error")
        self.refresh_data()

    def action_edit(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify("Select a case first.", severity="warning")
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

        try:
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
            self.app.notify(f"Case {case.number} updated.")
        except ApplicationError as exc:
            self.app.notify(str(exc), severity="error")
        self.refresh_data()

    def action_seal(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify("Select a case first.", severity="warning")
            return
        self.app.push_screen(
            TypedConfirmModal(f"Seal case {case.number} permanently?", case.number),
            lambda ok: self._sealed(case.number) if ok else None,
        )

    def _sealed(self, number: str) -> None:
        try:
            self._cases_svc.close_case(number, actor=None)
            self.app.notify(f"Case {number} sealed.")
        except ApplicationError as exc:
            self.app.notify(str(exc), severity="error")
        self.refresh_data()

    def action_archive(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify("Select a case first.", severity="warning")
            return
        self.app.push_screen(
            YesNoModal(f"Archive case {case.number}?"), lambda ok: self._archived(case.number) if ok else None
        )

    def _archived(self, number: str) -> None:
        try:
            self._cases_svc.delete_case(number)
            self.app.notify(f"Case {number} archived.")
        except ApplicationError as exc:
            self.app.notify(str(exc), severity="error")
        self.refresh_data()

    def action_purge(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify("Select a case first.", severity="warning")
            return
        self.app.push_screen(
            TypedConfirmModal(f"PURGE case {case.number}? Irreversible.", case.number),
            lambda ok: self._purged(case.number) if ok else None,
        )

    def _purged(self, number: str) -> None:
        try:
            self._cases_svc.delete_case(number, purge=True)
            self.app.notify(f"Case {number} purged.")
        except ApplicationError as exc:
            self.app.notify(str(exc), severity="error")
        self.refresh_data()

    def action_restore(self) -> None:
        case = self._selected()
        if case is None:
            self.app.notify("Select a case first.", severity="warning")
            return
        self.app.push_screen(
            YesNoModal(f"Restore archived case {case.number}?"),
            lambda ok: self._restored(case.number) if ok else None,
        )

    def _restored(self, number: str) -> None:
        try:
            self._cases_svc.restore_case(number)
            self.app.notify(f"Case {number} restored.")
        except ApplicationError as exc:
            self.app.notify(str(exc), severity="error")
        self.refresh_data()

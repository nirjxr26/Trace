"""Cases tab: live table + dossier + raw drawer + mutation forms."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Rule, Static

from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto, CaseFilterDto, CaseResponseDto, CaseUpdateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import ApplicationError
from trace_core.core.ui.renderers import format_india_datetime, sanitize_terminal
from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
from trace_core.tui.actions import run_guarded
from trace_core.tui.forms import CaseForm, RawModal, TextInputModal, TypedConfirmModal, YesNoModal
from trace_core.tui.theme import status_text
from trace_core.tui.widgets import DossierScroll, TablePane

TABLE_ID = "case-table"
CASE_HEADER_ID = "case-header"
TABLE_COLUMNS = (("Case #", 16), ("Status", 10))
_CASE_COMMAND_ALIASES = {"close": "seal"}
_NO_SELECTION = "Select a case first."
_TITLE_STYLE = f"bold {THEME_HEX['title']}"


class CasesView(TablePane[CaseResponseDto]):
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

    TABLE_ID = TABLE_ID
    HEADER_ID = CASE_HEADER_ID
    DETAIL_ID = "cases-right"
    SEARCH_ID = "case-search"
    COLUMNS = TABLE_COLUMNS

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._recent = False
        self._cases: list[CaseResponseDto] = []
        self._event_cache: dict[str, list] = {}
        self._event_total: dict[str, int] = {}

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

    def _query(self) -> list[CaseResponseDto]:
        query = self.query_one("#case-search", Input).value.strip() or None
        return self._cases_svc.list_cases(
            CaseFilterDto(search=query, include_deleted=True, limit=100, recent=self._recent)
        )

    def refresh_data(self) -> None:
        """Reload table + dossier. Called on mount, tab switch, and after every mutation."""
        self._event_cache.clear()
        self._event_total.clear()
        try:
            self._cases = self._query()
        except Exception as exc:  # boundary: every service failure becomes a toast, never a crash
            self.app.notify(str(exc), severity="error")
            return
        self.fill_table(self._cases, [c.number for c in self._cases])

    def row_cells(self, case: CaseResponseDto, selected: bool) -> list:  # type: ignore[no-untyped-def]
        from trace_core.core.ui.renderers import sanitize_terminal
        from trace_core.tui.theme import SELECT_PREFIX

        first = f"{SELECT_PREFIX}{case.number}" if selected else f"  {case.number}"
        return [sanitize_terminal(first), status_text(case.status, case.is_deleted)]

    def render_detail(self) -> None:
        from trace_core.tui.widgets import DossierScroll

        case = self._selected()
        if case is None:
            from trace_core.tui.theme import detail_placeholder

            self.query_one("#case-dossier", Static).update(
                detail_placeholder(bool(self._cases), "No cases found — press c to create.")
            )
            return
        events = self._dossier_events(case)
        rule = self.query_one("#cases-right", DossierScroll).divider()
        from trace_core.tui.theme import status_label, status_style

        body = Text()
        self._append_head(
            body, case, rule, status_label(case.status, case.is_deleted), status_style(case.status, case.is_deleted)
        )
        self._append_meta(body, case, rule)
        self._append_integrity(body, events, rule, case.number)
        self._append_history(body, case, events)
        self.query_one("#case-dossier", Static).update(body)

    def _append_integrity(self, body, events, rule, case_number) -> None:  # type: ignore[no-untyped-def]
        from trace_core.audit.verifier import verify_event
        from trace_core.tui.theme import integrity_line

        verified: bool | None = None if events is None else True
        if events:
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
        body.append_text(integrity_line(verified, len(events or ()), sampled=self._dossier_total(case_number)))
        body.append("\n")
        body.append(rule)
        body.append("\n")

    def _append_head(self, body, case, rule, status_label, status_color) -> None:  # type: ignore[no-untyped-def]
        # Identity + status + examiner. Panel padding is 1; one blank line per section.
        body.append(f"{sanitize_terminal(case.number)}\n", style=THEME_HEX["blue"])
        body.append(f"{sanitize_terminal(case.title or 'Untitled')}\n", style=_TITLE_STYLE)
        body.append("\u25cf ", style=status_color)
        body.append(f"{status_label}\n", style=f"bold {status_color}")
        body.append(rule)
        body.append("\n")
        body.append(f"{'Lead Examiner':<15} ", style="dim")
        body.append(f"{sanitize_terminal(case.lead_examiner or '\u2014')}\n", style=THEME_HEX["value"])
        body.append(f"{'Tags':<15} ", style="dim")
        if case.tags:
            body.append(sanitize_terminal(" ".join(f"#{t}" for t in case.tags)) + "\n", style=THEME_HEX["tag"])
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
        # None means the ledger could not be read, which is not the same as no records.
        if case.number not in self._event_cache:
            try:
                self._event_cache[case.number] = AuditService(self._manager).list_events(
                    AuditFilterDto(case_number=case.number, limit=6)
                )
            except ApplicationError:
                return None
        return self._event_cache[case.number]

    def _dossier_total(self, case_number: str) -> int | None:  # type: ignore[no-untyped-def]
        # Total records for this case, so the integrity line can name its window instead of
        # implying the whole history was checked. None when the count is unavailable.
        cached = self._event_total.get(case_number)
        if cached is not None:
            return cached
        try:
            total = AuditService(self._manager).count_events(AuditFilterDto(case_number=case_number))
        except ApplicationError:
            return None
        self._event_total[case_number] = total
        return total

    def _append_history(self, body, case, events) -> None:  # type: ignore[no-untyped-def]
        # HISTORY proof block shared by dossier renders.
        if events is None:
            body.append("\nHISTORY\n", style=THEME_TOKENS["accent"])
            body.append("Couldn't read the ledger for this case.\n")
            body.append("\n")
            return
        if not events:
            return
        from trace_core.audit.renderers import short_action_label
        from trace_core.core.ui.renderers import format_ledger_time, plural

        count = plural(len(events), "event")
        body.append(f"HISTORY \u00b7 {count}\n", style=THEME_TOKENS["accent"])
        for e in events[:5]:
            body.append(f"{format_ledger_time(e.ts)}  ", style="dim")
            body.append(f"{short_action_label(e.action)}", style=_TITLE_STYLE)
            body.append(f"  \u00b7  {sanitize_terminal(e.actor)}\n", style="dim")

    def run_command(self, command: str) -> None:
        """Entry for the palette. Unknown ids toast instead of vanishing."""
        name = _CASE_COMMAND_ALIASES.get(command.removeprefix("case-"), command.removeprefix("case-"))
        action = getattr(self, f"action_{name}", None)
        if callable(action) and getattr(action, "__name__", "").startswith("action_"):
            action()
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

    def action_recent(self) -> None:
        self._recent = not self._recent
        self.app.notify("Recent first on." if self._recent else "Recent first off.")
        self.refresh_data()

    def _require_selected(self) -> CaseResponseDto | None:
        case = self._selected()
        if case is None:
            self.app.notify(_NO_SELECTION, severity="warning")
        return case

    def action_raw(self) -> None:
        case = self._require_selected()
        if case is None:
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
        case = self._require_selected()
        if case is None:
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
        case = self._require_selected()
        if case is None:
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
        from trace_core.audit.anchor import describe_anchor

        def _seal() -> str:
            self._cases_svc.close_case(number, reason=reason, actor=None)
            anchor = describe_anchor(self._cases_svc.session_manager, number)
            return f"Case {number} sealed. {anchor or 'Anchor: UNKNOWN.'}"

        run_guarded(self, _seal)

    def action_archive(self) -> None:
        case = self._require_selected()
        if case is None:
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
        case = self._require_selected()
        if case is None:
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
        case = self._require_selected()
        if case is None:
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

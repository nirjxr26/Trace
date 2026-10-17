"""Cases tab: live table + dossier + raw drawer + mutation forms."""

import json
from datetime import datetime
from typing import NamedTuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import DataTable, Input, Rule, Static

from trace_core.audit.domain import AuditAction
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


class _LinkedDevice(NamedTuple):
    """One device's relationship to a case, as both dossiers present it."""

    node: str
    label: str
    model: str
    size: str
    current: bool
    linked_at: datetime
    linked_by: str
    capacity_bytes: int | None = None

    @property
    def heading(self) -> str:
        from trace_core.devices.renderers import device_heading

        return device_heading(self.node, self.model or None, self.capacity_bytes)


def _device_row(node: str, label: str, observed: dict, current: bool, at, who: str) -> _LinkedDevice:
    """One dossier row. Model and size come from the newest observation for that node.

    The model is shown exactly as recorded. `readable_model` shortens a vendor part number
    into a product name, which is right for a narrow device-list column and wrong here: in a
    dossier the part number is what identifies the drive, so `Micron_2400_MTFDKBA512QFM` must
    not be reduced to `Micron`.
    """
    from trace_core.devices.renderers import format_bytes

    record = observed.get(node)
    model = record.model if record is not None and record.model else ""
    size = format_bytes(record.capacity_bytes) if record is not None else ""
    capacity = record.capacity_bytes if record is not None else None
    return _LinkedDevice(node, label, model, size, current, at, who, capacity)


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
        self._device_cache: dict[str, list[_LinkedDevice]] = {}
        self._case_versions: dict[str, datetime] = {}
        self._detail_width: int | None = None

    @property
    def _cases_svc(self) -> CaseService:
        return CaseService(self._manager)

    def compose(self) -> ComposeResult:
        with Horizontal(id="cases-top"):
            with Vertical(id="cases-left"):
                yield Input(placeholder="Search cases...", id="case-search")
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
        try:
            cases = self._query()
        except Exception as exc:  # boundary: every service failure becomes a toast, never a crash
            self.app.notify(str(exc), severity="error")
            return
        fresh = {c.number: c.updated_at for c in cases}
        if fresh != self._case_versions:
            for number in set(self._case_versions) | set(fresh):
                if self._case_versions.get(number) != fresh.get(number):
                    self.drop_dossier(number)
            self._case_versions = fresh
        self._cases = cases
        self.fill_table(self._cases, [c.number for c in self._cases])

    def row_cells(self, case: CaseResponseDto, selected: bool) -> list:  # type: ignore[no-untyped-def]
        from trace_core.core.ui.renderers import sanitize_terminal
        from trace_core.tui.theme import SELECT_PREFIX

        first = f"{SELECT_PREFIX}{case.number}" if selected else f"  {case.number}"
        return [sanitize_terminal(first), status_text(case.status, case.is_deleted)]

    def on_resize(self, event: Resize) -> None:
        """Dividers are baked for one width; rebuild them when the width moves."""
        from trace_core.tui.widgets import DossierScroll

        width = self.query_one("#cases-right", DossierScroll).content_region.width
        if width == self._detail_width:
            return
        self._detail_width = width
        self.render_detail()

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
        if case.closed_at:
            body.append(f"{'Closed':<15} ", style="dim")
            body.append(f"{format_india_datetime(case.closed_at)}\n")
            if case.closure_reason:
                body.append(f"{'Reason':<15} ", style="dim")
                body.append(f"{sanitize_terminal(case.closure_reason)}\n")
        if case.description:
            body.append(rule)
            body.append("\nDESCRIPTION\n", style=THEME_TOKENS["accent"])
            body.append(f"  {sanitize_terminal(case.description)}\n")
        if case.notes:
            body.append(rule)
            body.append("\nNOTES\n", style=THEME_TOKENS["accent"])
            body.append(f"  {sanitize_terminal(case.notes)}\n")
        self._append_linked_devices(body, rule, self._case_devices(case.number))

    def _append_linked_devices(self, body, rule, devices) -> None:  # type: ignore[no-untyped-def]
        if not devices:
            return
        body.append(rule)
        body.append("\nLINKED DEVICE\n", style=THEME_TOKENS["accent"])
        for row in devices:
            heading = row.heading
            body.append(f"  {sanitize_terminal(heading)}\n", style=None if row.current else "dim")
            if row.label:
                body.append(f"    {'Label':<10}", style="dim")
                body.append(f"{sanitize_terminal(row.label)}\n", style=None if row.current else "dim")

    def drop_dossier(self, case_number: str) -> None:
        self._event_cache.pop(case_number, None)
        self._event_total.pop(case_number, None)
        self._device_cache.pop(case_number, None)

    def _case_devices(self, case_number: str) -> list[_LinkedDevice]:
        """Devices ever filed under this case as (node, label, model, size, current).

        The link table holds current state; the ledger holds history. A device that was
        filed and then unlinked still has a DEVICE_LINKED event, so it stays in the record
        dimmed rather than vanishing - unlinking removes the claim, not the history of it.

        Model and size come from the newest observation, not the live adapter: what a disk
        was recorded as outlives the disk being unplugged. A serial is deliberately absent -
        it identifies a device to a machine, not a disk to someone reading a dossier, and it
        is long enough to swamp the line.
        """
        if case_number in self._device_cache:
            return self._device_cache[case_number]
        from trace_core.devices.helpers import do_case_links, do_observed_devices

        rows: list[_LinkedDevice] = []
        try:
            observed = do_observed_devices(self._manager)
            current = do_case_links(self._manager, case_number)
            rows = [
                _device_row(link.node, link.label or "", observed, True, link.linked_at, link.linked_by)
                for link in current
            ]
            linked_now = {row.node for row in rows}
            for node, (at, who) in self._previously_linked(case_number).items():
                if node not in linked_now:
                    rows.append(_device_row(node, "", observed, False, at, who))
            self._device_cache[case_number] = rows
            return rows
        except Exception:
            return []

    def _previously_linked(self, case_number: str) -> dict[str, tuple[datetime, str]]:
        """node -> (linked at, linked by) from the ledger.

        Device link events carry the case as their subject, so the linkage history is
        queryable per case and survives the link row being deleted.
        """
        nodes: dict[str, tuple[datetime, str]] = {}
        for event in AuditService(self._manager).list_events(
            AuditFilterDto(case_number=case_number, action=AuditAction.DEVICE_LINKED, limit=500)
        ):
            try:
                details = json.loads(event.payload_json).get("details", {})
            except (TypeError, ValueError):
                continue
            node = details.get("node")
            if node:
                nodes.setdefault(str(node), (event.ts, event.actor))
        return nodes

    def _dossier_events(self, case):  # type: ignore[no-untyped-def]
        # Recent audit events for the dossier, cached per case; dropped when the row
        # changes on refresh. None means the ledger could not be read, which is not
        # the same as no records.
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

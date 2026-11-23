"""Audit tab: live ledger stream + detail + scope + raw drawer."""

from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Resize
from textual.widgets import DataTable, Input, Static

from trace_core.audit.dto import AuditEventDto, AuditEventSummaryDto, AuditFilterDto
from trace_core.audit.events import parse_details
from trace_core.audit.renderers import action_title, subject_case_label
from trace_core.audit.service import AuditService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import sanitize_terminal
from trace_core.core.ui.theme import THEME_TOKENS
from trace_core.tui.actions import confirm_overwrite, run_guarded
from trace_core.tui.design.text import kv_row, section_head
from trace_core.tui.design.tokens import LABEL_MD, LABEL_SM
from trace_core.tui.design.widgets import ListDetailPane, sync_detail_width, unknown_command
from trace_core.tui.forms import RawModal, TextInputModal
from trace_core.tui.widgets import DossierScroll, TablePane

if TYPE_CHECKING:
    from trace_core.audit.helpers import BundleReceipt

TABLE_ID = "audit-table"
AUDIT_HEADER_ID = "audit-header"
AUDIT_DETAIL_ID = "audit-detail"
TABLE_COLUMNS = (("Seq", 7), ("Event", 24))
PAGE_ROWS = 200
PREFETCH_LINES = 20


class AuditView(TablePane[AuditEventSummaryDto]):
    """Top: stream table. Bottom: selected event detail. Filters on top."""

    BINDINGS = [
        Binding("s", "scope", "Scope case"),
        Binding("slash", "search", "Search"),
        Binding("v", "raw", "Raw"),
        Binding("e", "export", "Export"),
        Binding("a", "anchor", "Anchor"),
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
        self._exhausted = False
        self._capped = False
        self._total = 0
        self._detail_seq: int | None = None
        self._detail: AuditEventDto | None = None
        self._observed_cache: dict | None = None
        self._detail_width: int | None = None
        self._last_sealed: str | None = None

    @property
    def _svc(self) -> AuditService:
        return AuditService(self._manager)

    def compose(self) -> ComposeResult:
        from trace_core.tui.widgets import PagedTable

        def build_table() -> PagedTable:
            table = PagedTable(id=TABLE_ID, cursor_type="row", show_header=False, classes="pane-table")
            table.on_scrolled = self._extend
            return table

        yield ListDetailPane(
            top_id="audit-main",
            left_id="audit-left",
            right_id="audit-right",
            detail_id=AUDIT_DETAIL_ID,
            detail_text="Select an event…",
            search_id="audit-search",
            search_placeholder="Search actor, action, case, device, seq...",
            header_id=AUDIT_HEADER_ID,
            table_factory=build_table,
            left_extra=(Static("", id="audit-scope"),),
        )

    def _filter(self, before_seq: int | None = None, limit: int = PAGE_ROWS) -> AuditFilterDto:
        return AuditFilterDto(
            case_number=self._scope,
            search=self.query_one("#audit-search", Input).value.strip() or None,
            before_seq=before_seq,
            limit=limit,
        )

    def _window(self, before_seq: int | None) -> list[AuditEventSummaryDto]:
        return self._svc.list_event_summaries(self._filter(before_seq))

    def displayed_count(self) -> int:
        return self._total

    def refresh_data(self) -> None:
        """Reload stream + detail. Called on mount, tab switch, and scope change."""
        scope_widget = self.query_one("#audit-scope", Static)
        scope_widget.update(f"Scoped: {self._scope}   (s clears)" if self._scope else "")
        scope_widget.display = bool(self._scope)
        try:
            rows = self._window(None)
        except Exception as exc:  # boundary: every service failure becomes a toast, never a crash
            self.app.notify(str(exc), severity="error")
            return
        self._exhausted = len(rows) < PAGE_ROWS
        self._capped = False
        self.fill_table(rows, [str(e.seq) for e in rows])
        self._total = self._total_ledger()
        self._update_header()

    def _total_ledger(self) -> int:
        try:
            return self._svc.count_events(self._filter())
        except Exception as exc:  # boundary: the stream still loads, but a wrong total is never silent
            self.app.notify(f"Audit total unavailable: {exc}", severity="warning")
            return len(self._items)

    def _extend(self) -> None:
        table = self._table()
        if self._exhausted or not self._items:
            return
        at_last_row = table.cursor_row is not None and table.cursor_row >= len(self._items) - 1
        near_end = table.max_scroll_y > 0 and table.max_scroll_y - table.scroll_offset.y <= PREFETCH_LINES
        if not (at_last_row or near_end):
            return
        oldest = self._items[-1].seq
        if len(self._items) >= PAGE_ROWS * 5:
            if not self._capped:
                self._capped = True
                self.app.notify(
                    f"Showing newest {PAGE_ROWS * 5} — refine search or export for older records.",
                    severity="warning",
                )
            return
        try:
            rows = self._window(oldest)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
            return
        self._exhausted = len(rows) < PAGE_ROWS
        self.append_rows(rows, [str(e.seq) for e in rows])

    def _selected_event(self) -> AuditEventDto | None:
        row = self._selected()
        if row is None:
            return None
        if self._detail_seq != row.seq:
            self._detail = self._svc.get_by_seq(row.seq)
            self._detail_seq = row.seq
        return self._detail

    def row_cells(self, event: AuditEventSummaryDto, selected: bool) -> list:  # type: ignore[no-untyped-def]
        from trace_core.audit.renderers import short_action_label
        from trace_core.tui.theme import SELECT_PREFIX

        prefix = SELECT_PREFIX if selected else "  "
        return [f"{prefix}{event.seq}", short_action_label(event.action)]

    def _observed(self):  # type: ignore[no-untyped-def]
        """Newest observation per node, fetched once per session for this view."""
        if self._observed_cache is None:
            from trace_core.devices.helpers import do_observed_devices

            try:
                self._observed_cache = do_observed_devices(self._manager)
            except Exception:
                self._observed_cache = {}
        return self._observed_cache

    def on_resize(self, event: Resize) -> None:
        """Dividers are baked for one width; rebuild them when the width moves."""
        if not sync_detail_width(self, "audit-right"):
            return
        self.render_detail()

    @staticmethod
    def _detail_row(body: Text, label: str, value: str) -> None:
        kv_row(body, label, value, LABEL_MD)

    def _append_integrity(
        self, body: Text, event: AuditEventDto, intact: bool | None, hash_ok: bool | None, key_problem: str
    ) -> None:
        from trace_core.tui.theme import DOT_BAD

        section_head(body, "INTEGRITY VERIFICATION")
        if hash_ok is True:
            chain = "Valid"
        elif hash_ok is False:
            chain = "Mismatch"
        else:
            chain = "Not verified"
        self._detail_row(body, "Chain status", chain)
        signature = "Verified" if event.signature and intact is True and not key_problem else "Not verified"
        self._detail_row(body, "Signature", signature)
        if key_problem:
            signing = "Development key" if key_problem == "insecure_key" else "Key unavailable"
            self._detail_row(body, "Signing key", signing)
            body.append("This is a key problem, not evidence of tampering.\n", style=DOT_BAD)

    @staticmethod
    def _detail_verification(e: AuditEventDto) -> tuple[bool | None, bool | None, str]:
        from trace_core.audit.verifier import row_key_problem, verify_event

        try:
            intact = verify_event(
                e.payload_json,
                e.payload_hash,
                e.prev_chain,
                e.chain_hash,
                e.seq,
                signature=e.signature,
                key_id=e.key_id,
            )
        except Exception:
            intact = None
        try:
            hash_ok = verify_event(e.payload_json, e.payload_hash, e.prev_chain, e.chain_hash, e.seq)
        except Exception:
            hash_ok = None
        key_problem = ""
        if intact is not None:
            try:
                key_problem = (
                    row_key_problem(
                        e.payload_json,
                        e.payload_hash,
                        e.prev_chain,
                        e.chain_hash,
                        e.seq,
                        signature=e.signature,
                        key_id=e.key_id,
                    )
                    or ""
                )
            except Exception:
                key_problem = ""
        return intact, hash_ok, key_problem

    def _append_event_details(
        self, body: Text, e: AuditEventDto, reason: str, utc: str, ist: str, unreadable: bool
    ) -> None:
        body.append(f"#{e.seq} · {action_title(e.action.value)}\n", style=THEME_TOKENS["accent"])
        body.append(f"{reason or 'No reason recorded'}\n", style="dim")
        section_head(body, "EVENT DETAILS")
        self._detail_row(body, "Event", e.action.value)
        self._detail_row(body, "Sequence", str(e.seq))
        self._detail_row(body, "Case", subject_case_label(e.subject_case_number))
        self._detail_row(body, "Actor", e.actor)
        self._detail_row(body, "Timestamp", f"{utc} / {ist}")
        self._detail_row(body, "Reason", reason)
        if unreadable:
            body.append("unreadable — details cannot be shown\n", style="dim")

    def _append_subject_device(self, body: Text, e: AuditEventDto, details: dict) -> str:
        from trace_core.devices.renderers import device_heading, format_bytes

        section_head(body, "SUBJECT DEVICE")
        node = str(details.get("node") or "")
        if node:
            record = self._observed().get(node)
            serial = e.subject_device_serial or str(details.get("serial") or "")
            capacity = record.capacity_bytes if record else None
            body.append(f"  {sanitize_terminal(device_heading(node, record.model if record else None, capacity))}\n")
            self._detail_row(body, "Node", node)
            self._detail_row(body, "Serial", serial)
            self._detail_row(body, "Capacity", format_bytes(capacity) if capacity is not None else "")
            self._detail_row(body, "Evidence label", str(details.get("label") or ""))
        else:
            body.append("  No subject device recorded.\n", style="dim")
        return node

    def _append_recorded_changes(self, body: Text, details: dict) -> None:
        from trace_core.audit.renderers import format_change_value
        from trace_core.core.ui.renderers import fit_text

        changed = details.get("changed", [])
        if changed:
            section_head(body, f"RECORDED CHANGES · {len(changed)}")
            before, after = details.get("before", {}), details.get("after", {})
            for field in changed:
                old = fit_text(format_change_value(before.get(field)), 42)
                new = fit_text(format_change_value(after.get(field)), 42)
                self._detail_row(body, field.replace("_", " ").title(), f"{old} → {new}")

    def _append_related_records(self, body: Text, e: AuditEventDto, details: dict, node: str) -> None:
        section_head(body, "RELATED RECORDS")
        related = self._observed().get(node) if node else None
        device = str(details.get("model") or (related.model if related else ""))
        self._detail_row(body, "Case", subject_case_label(e.subject_case_number))
        self._detail_row(body, "Device", device)
        self._detail_row(body, "Imaging", str(details.get("operation_id") or ""))

    def render_detail(self) -> None:
        from datetime import UTC
        from zoneinfo import ZoneInfo

        e = self._selected_event()
        if e is None:
            from trace_core.tui.theme import detail_placeholder

            self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._items), "No audit events found — create or close a case.")
            )
            return
        details = parse_details(e.payload_json)
        unreadable = details is None
        details = details or {}
        intact, hash_ok, key_problem = self._detail_verification(e)
        body = Text()
        utc = e.ts.astimezone(UTC).strftime("%H:%M:%S UTC")
        ist = e.ts.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S IST")
        reason = str(details.get("reason") or "").strip()
        self._append_event_details(body, e, reason, utc, ist, unreadable)
        node = self._append_subject_device(body, e, details)
        self._append_recorded_changes(body, details)
        self._append_integrity(body, e, intact, hash_ok, key_problem)
        self._append_related_records(body, e, details, node)
        self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(body)

    def run_command(self, command: str) -> None:
        """Entry for the palette."""
        action = command.removeprefix("audit-")
        if action == "export":
            self.action_export()
        elif action == "anchor":
            self.action_anchor()
        else:
            unknown_command(self, command)

    def action_anchor(self) -> None:
        self.app.push_screen(
            TextInputModal("Anchor file to verify the tail against", "/path/to/anchor.json", required=True),
            self._anchor_verified,
        )

    def _anchor_verified(self, path: str | None) -> None:
        if not path:
            return
        from trace_core.audit.anchor import verify_against_anchor
        from trace_core.audit.helpers import enforce_verify_policy

        def _run() -> str:
            svc = self._svc
            res = svc.verify()
            verify_against_anchor(svc, res, path)
            enforce_verify_policy(res)
            return f"Ledger verified; tail matches {sanitize_terminal(path)}."

        run_guarded(self, _run)

    def action_scope(self) -> None:
        self.app.push_screen(TextInputModal("Scope to case (blank clears)", "2026-CR-0001"), self._scoped)

    def _scoped(self, value: str | None) -> None:
        self._scope = value or None
        self.refresh_data()

    @on(DataTable.RowHighlighted)
    def _grown(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == self.TABLE_ID:
            self._extend()

    def action_raw(self) -> None:
        e = self._selected_event()
        if e is None:
            from trace_core.tui.theme import detail_placeholder

            self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._items), "No audit events found — create or close a case.")
            )
            return
        self.app.push_screen(RawModal(f"seq {e.seq} payload", e.payload_json))

    def action_export(self) -> None:
        from trace_core.tui.forms import ExportHubModal

        self.app.push_screen(ExportHubModal("Whole ledger — tab scope and search do not apply."), self._export_chosen)

    def _export_chosen(self, choice: str | None) -> None:
        from trace_core.audit.helpers import default_export_path
        from trace_core.tui.forms import TextInputModal

        if choice == "plain":
            self.app.push_screen(
                TextInputModal("Export bundle to", str(default_export_path()), required=True),
                self._plain_chosen,
            )
        elif choice == "sealed":
            self.app.push_screen(
                TextInputModal("Sealed bundle to", str(default_export_path(sealed=True)), required=True),
                self._sealed_chosen,
            )
        elif choice == "open":
            self.app.push_screen(
                TextInputModal("Sealed bundle to open", self._last_sealed or "bundle.jsonl.sealed", required=True),
                self._open_chosen,
            )

    def _plain_chosen(self, path: str | None) -> None:
        if path:
            confirm_overwrite(self, path, lambda: self._export_to(path, None))

    def _sealed_chosen(self, path: str | None) -> None:
        from trace_core.tui.forms import TextInputModal

        if not path:
            return
        self.app.push_screen(
            TextInputModal("Passphrase", "not stored, never logged", required=True, password=True, confirm=True),
            lambda value: self._sealed_confirmed(path, value),
        )

    def _sealed_confirmed(self, path: str, passphrase: str | None) -> None:
        from trace_core.audit.helpers import sealed_destination

        if not passphrase:
            return
        confirm_overwrite(self, str(sealed_destination(path)), lambda: self._export_to(path, passphrase))

    def _open_chosen(self, path: str | None) -> None:
        from trace_core.audit.helpers import plain_destination

        if not path:
            return
        confirm_overwrite(self, str(plain_destination(path)), lambda: self._ask_open_passphrase(path))

    def _ask_open_passphrase(self, path: str) -> None:
        from trace_core.tui.forms import TextInputModal

        self.app.push_screen(
            TextInputModal("Passphrase", "exact passphrase used when sealing", required=True, password=True),
            lambda value: self._decrypt_from(path, value) if value else None,
        )

    def _export_to(self, path: str, passphrase: str | None) -> None:
        from trace_core.audit.helpers import do_export

        try:
            receipt = do_export(self._svc, path, passphrase, force=True)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
            return
        from trace_core.audit.helpers import next_step_for

        message = "Bundle sealed." if receipt.sealed else "Bundle exported."
        if receipt.sealed:
            self._last_sealed = str(receipt.path)
        self.app.notify(message)
        self._show_receipt(receipt, message, next_step_for(receipt))

    def _decrypt_from(self, in_path: str, passphrase: str) -> None:
        from trace_core.audit.helpers import do_decrypt, plain_destination

        try:
            receipt = do_decrypt(in_path, str(plain_destination(in_path)), passphrase, force=True)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
            return
        message = "Bundle decrypted."
        self.app.notify(message)
        self._show_receipt(receipt, message)

    def _show_receipt(self, receipt: "BundleReceipt", message: str, next_step: str = "") -> None:
        from trace_core.audit.helpers import receipt_rows

        rows = receipt_rows(receipt)
        if next_step:
            rows.append(("Next", next_step))
        pane = self.query_one("#audit-right", DossierScroll)
        rule = pane.divider()
        body = Text()
        body.append(message + "\n", style=THEME_TOKENS["accent"])
        body.append(rule)
        body.append("\n")
        for key, value in rows:
            kv_row(body, key, value, LABEL_SM)
        self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(body)

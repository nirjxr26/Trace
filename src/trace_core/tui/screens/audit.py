"""Audit tab: live ledger stream + detail + scope + raw drawer."""

from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import DataTable, Input, Rule, Static

from trace_core.audit.dto import AuditEventDto, AuditEventSummaryDto, AuditFilterDto
from trace_core.audit.events import parse_details
from trace_core.audit.renderers import action_title, subject_case_label
from trace_core.audit.service import AuditService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import format_india_datetime, sanitize_terminal
from trace_core.core.ui.theme import THEME_TOKENS
from trace_core.tui.actions import confirm_overwrite, run_guarded
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
        from trace_core.tui.widgets import DossierScroll, PagedTable

        table = PagedTable(id=TABLE_ID, cursor_type="row", show_header=False)
        table.on_scrolled = self._extend
        with Horizontal(id="audit-main"):
            with Vertical(id="audit-left"):
                yield Input(placeholder="Search actor, action, case, device, seq...", id="audit-search")
                yield Static("", id="audit-scope")
                yield Static("", id=AUDIT_HEADER_ID, classes="table-head")
                yield Rule()
                yield table
            with DossierScroll(id="audit-right"):
                yield Static("Select an event…", id=AUDIT_DETAIL_ID)

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

    def _append_device(self, body, details, rule: Text) -> None:  # type: ignore[no-untyped-def]
        """DEVICE section for an event about a device.

        A DEVICE_LINKED row names the case but not the drive, so selecting one showed a
        link with nothing on the other end of it. The node lives in the payload details;
        the model and capacity come from the newest observation for that node.
        """
        node = str(details.get("node") or "")
        if not node:
            return
        from trace_core.devices.renderers import device_heading

        record = self._observed().get(node)
        body.append(rule)
        body.append("\nDevice Linked\n", style=THEME_TOKENS["accent"])
        heading = device_heading(node, record.model if record else None, record.capacity_bytes if record else None)
        body.append(f"  {sanitize_terminal(heading)}\n")
        label = details.get("label")
        if label:
            body.append(f"  {'Label':<10}", style="dim")
            body.append(f"{sanitize_terminal(str(label))}\n")

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
        width = self.query_one("#audit-right", DossierScroll).content_region.width
        if width == self._detail_width:
            return
        self._detail_width = width
        self.render_detail()

    def render_detail(self) -> None:
        from trace_core.audit.verifier import row_key_problem, verify_event
        from trace_core.tui.theme import DOT_BAD, DOT_OK, integrity_line

        e = self._selected_event()
        if e is None:
            from trace_core.tui.theme import detail_placeholder

            self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._items), "No audit events found — create or close a case.")
            )
            return
        details = parse_details(e.payload_json)
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
        pane = self.query_one("#audit-right", DossierScroll)
        rule = pane.divider()
        body = Text()
        body.append(f"#{e.seq}  {action_title(e.action.value)}\n", style=THEME_TOKENS["accent"])
        body.append(rule)
        body.append("\n")
        body.append("Case      ", style="dim")
        body.append(f"{sanitize_terminal(subject_case_label(e.subject_case_number))}\n")
        body.append("Actor     ", style="dim")
        body.append(f"{sanitize_terminal(e.actor)}\n")
        body.append("Timestamp ", style="dim")
        body.append(f"{format_india_datetime(e.ts)}\n")
        body.append("Event     ", style="dim")
        body.append(f"{e.action.value}\n")
        if details is None:
            body.append("Payload   ", style="dim")
            body.append("unreadable — details cannot be shown\n")
            details = {}
        reason = (details.get("reason") or "").strip()
        if reason:
            body.append("Reason    ", style="dim")
            body.append(f"{sanitize_terminal(reason)}\n")
        self._append_device(body, details, rule)
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
        body.append("\nSELF-CHECK\n", style=THEME_TOKENS["accent"])
        key_problem = None
        if intact is not None:
            try:
                key_problem = row_key_problem(
                    e.payload_json,
                    e.payload_hash,
                    e.prev_chain,
                    e.chain_hash,
                    e.seq,
                    signature=e.signature,
                    key_id=e.key_id,
                )
            except Exception:
                key_problem = None
        if key_problem == "insecure_key":
            body.append("⚠ ", style=DOT_BAD)
            body.append("SIGNED WITH THE DEVELOPMENT KEY\n", style="bold")
            body.append("Signed with the shipped development key, which is public.\n", style="dim")
            body.append("This is a key problem, not evidence of tampering.\n", style="dim")
        elif key_problem == "signing_key" or (key_problem is not None and key_problem.startswith("key:")):
            body.append("⚠ ", style=DOT_BAD)
            body.append("SIGNING KEY UNAVAILABLE\n", style="bold")
            if key_problem == "signing_key":
                body.append("The key this ledger was signed with is not the active key.\n", style="dim")
            else:
                body.append("The key this record was signed with is not in the keystore.\n", style="dim")
            body.append("This is a key problem, not evidence of tampering.\n", style="dim")
        else:
            body.append_text(integrity_line(intact, 0 if intact is not True else 1))
        body.append("\n")
        self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(body)

    def run_command(self, command: str) -> None:
        """Entry for the palette."""
        action = command.removeprefix("audit-")
        if action == "export":
            self.action_export()
        elif action == "anchor":
            self.action_anchor()
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

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

        if receipt.sealed:
            self._last_sealed = str(receipt.path)
        self._show_receipt(
            receipt,
            "Bundle sealed." if receipt.sealed else "Bundle exported.",
            next_step_for(receipt),
        )

    def _decrypt_from(self, in_path: str, passphrase: str) -> None:
        from trace_core.audit.helpers import do_decrypt, plain_destination

        try:
            receipt = do_decrypt(in_path, str(plain_destination(in_path)), passphrase, force=True)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
            return
        self._show_receipt(receipt, "Bundle decrypted.")

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
            body.append(f"{key:<10}", style="dim")
            body.append(f"{sanitize_terminal(value)}\n")
        self.query_one(f"#{AUDIT_DETAIL_ID}", Static).update(body)

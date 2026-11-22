"""Devices tab: enumeration, fingerprint detail, and the write-protection gate.

Every service call goes through the same `helpers.do_*` cores the Typer CLI and the
REPL use, so the three surfaces cannot drift. Hardware strings are attacker-controlled
bytes, so every value reaching the terminal goes through `sanitize_terminal`.
"""

from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Resize
from textual.timer import Timer
from textual.widgets import DataTable, Input, Static
from textual.worker import Worker

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import format_india_datetime, sanitize_terminal
from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
from trace_core.devices.dto import DeviceInfoDto, InspectionDto, ObservationDto, WpCheckDto
from trace_core.devices.renderers import display_node, format_bytes, readable_model
from trace_core.tui.actions import confirm_overwrite, run_guarded
from trace_core.tui.design.text import NO_SELECTION_DEVICE, kv_row, section_head
from trace_core.tui.design.tokens import LABEL_MD
from trace_core.tui.design.widgets import ListDetailPane, sync_detail_width, unknown_command
from trace_core.tui.widgets import TablePane, active_tab

TABLE_ID = "device-table"
DEVICE_HEADER_ID = "device-header"
DEVICE_DETAIL_ID = "device-detail"
DEVICE_SUMMARY_ID = "device-summary"
TABLE_COLUMNS = (("Device", 15), ("Size", 9))
MAX_PICKER_ROWS = 200
POLL_SECONDS = 1.0
SELECT_DEVICE_FIRST = NO_SELECTION_DEVICE


def _device_prompt(prefix: str, node: str, suffix: str) -> Text:
    prompt = Text(prefix)
    prompt.append(sanitize_terminal(node), style=THEME_HEX["blue"])
    prompt.append(suffix)
    return prompt


def _display_name(device: DeviceInfoDto) -> str:
    if device.model_hint:
        return readable_model(device.model_hint)
    return display_node(device.node)


class DevicesView(TablePane[DeviceInfoDto]):
    """Left: enumerated devices. Right: fingerprint, then the write-protection gate."""

    BINDINGS = [
        Binding("i", "inspect", "Inspect"),
        Binding("c", "check", "Check"),
        Binding("a", "acknowledge", "Acknowledge"),
        Binding("k", "kind", "Kind"),
        Binding("l", "link", "Link case"),
        Binding("u", "unlink", "Unlink case"),
    ]

    TABLE_ID = TABLE_ID
    HEADER_ID = DEVICE_HEADER_ID
    DETAIL_ID = "device-right"
    SEARCH_ID = "device-search"
    COLUMNS = TABLE_COLUMNS

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._kind = "all"
        self._gate: WpCheckDto | None = None
        self._gate_node: str | None = None
        self._inspected: InspectionDto | None = None
        self._refresh_timer: Timer | None = None
        self._scan_worker: Worker[None] | None = None
        self._last_token: tuple[str, ...] | None = None
        self._scan_token: tuple[str, ...] | None = None
        self._scanning = False
        self._scan_pending = False
        self._scan_generation = 0
        self._all_devices: list[DeviceInfoDto] = []
        self._cases_cache: dict[str, list[str]] = {}
        self._serials: dict[str, str] = {}
        self._history: list[ObservationDto] = []
        self._detail_width: int | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_timer = self.set_interval(POLL_SECONDS, self._poll_devices)

    def on_unmount(self) -> None:
        self._scan_generation += 1
        self._scanning = False
        self._scan_pending = False
        self._scan_token = None
        self._last_token = None
        if self._scan_worker is not None:
            self._scan_worker.cancel()
            self._scan_worker = None
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        super().on_unmount()

    def compose(self) -> ComposeResult:
        yield ListDetailPane(
            top_id="device-main",
            left_id="device-left",
            right_id="device-right",
            detail_id=DEVICE_DETAIL_ID,
            detail_text="Select a device…",
            search_id="device-search",
            search_placeholder="Search node or model...",
            header_id=DEVICE_HEADER_ID,
            table_factory=lambda: DataTable(id=TABLE_ID, cursor_type="row", show_header=False, classes="pane-table"),
            left_extra=(Static("", id=DEVICE_SUMMARY_ID, classes="muted"),),
        )

    def activate(self) -> None:
        self._refresh_if_changed()

    def refresh_data(self) -> None:
        self._start_scan(force=True)

    def _poll_devices(self) -> None:
        if active_tab(self) != "devices":
            return
        self._refresh_if_changed(quiet=True)

    def _refresh_if_changed(self, *, quiet: bool = False) -> None:
        token = self._token()
        if self._scanning:
            if token is not None and self._scan_token is not None and token != self._scan_token:
                self._scan_pending = True
            return
        if token is not None and token == self._last_token:
            return
        self._start_scan(token, quiet=quiet)

    def _start_scan(
        self,
        token: tuple[str, ...] | None = None,
        *,
        force: bool = False,
        quiet: bool = False,
    ) -> None:
        if self._scanning:
            if force:
                self._scan_pending = True
            return
        if token is None:
            token = self._token()
        self._scanning = True
        self._scan_pending = False
        self._scan_token = token
        self._scan_generation += 1
        self._render_summary()
        self._scan_worker = self.run_worker(
            self._scan(self._scan_generation, self._kind, token, quiet),
            name="device-scan",
            group="device-scan",
        )

    async def _scan(self, generation: int, kind: str, token: tuple[str, ...] | None, quiet: bool) -> None:
        import asyncio

        from trace_core.devices.helpers import do_enumerate, do_observed_devices

        error: Exception | None = None
        devices: list[DeviceInfoDto] = []
        try:
            observed = do_observed_devices(self._manager)
            devices = await asyncio.to_thread(do_enumerate, self._manager, kind, observed=observed)
        except Exception as exc:  # boundary: a service failure becomes a toast, never a crash
            error = exc
        if generation != self._scan_generation or not self.is_attached:
            return
        self._scan_worker = None
        self._scanning = False
        if error is not None:
            if not quiet:
                self.app.notify(str(error), severity="error")
            self._render_summary()
        elif kind != self._kind:
            self._scan_pending = True
            self._render_summary()
        else:
            self._last_token = token
            self._all_devices = devices
            self._serials = {d.node: d.serial for d in devices if d.serial}
            self._render_devices()
        if self._scan_pending:
            self._scan_pending = False
            self._start_scan(quiet=True)

    def search_changed(self) -> None:
        self._render_devices()

    def _token(self) -> tuple[str, ...] | None:
        from trace_core.devices.helpers import do_change_token

        try:
            return do_change_token(self._manager)
        except Exception:
            return None

    def _render_devices(self) -> None:
        query = self.query_one("#device-search", Input).value.strip().lower()
        devices = self._all_devices
        if query:
            devices = [
                d
                for d in devices
                if query in d.node.lower() or query in (d.model_hint or "").lower() or query in (d.serial or "").lower()
            ]
        self._render_list(devices)

    def _render_list(self, devices: list[DeviceInfoDto]) -> None:
        self._render_summary()
        self.fill_table(devices, [d.node for d in devices])

    def _render_summary(self) -> None:
        summary = self.query_one(f"#{DEVICE_SUMMARY_ID}", Static)
        label = f"kind: {self._kind}"
        summary.update(f"{label} · scanning…" if self._scanning else label)

    def row_cells(self, device: DeviceInfoDto, selected: bool) -> list:  # type: ignore[no-untyped-def]
        from trace_core.core.ui.renderers import fit_text
        from trace_core.tui.theme import SELECT_PREFIX

        prefix = SELECT_PREFIX if selected else "  "
        width = TABLE_COLUMNS[0][1] - len(prefix)
        name = fit_text(sanitize_terminal(_display_name(device)), width)
        return [f"{prefix}{name}", format_bytes(device.size_bytes)]

    def on_resize(self, event: Resize) -> None:
        """Dividers are baked for one width; rebuild them when the width moves."""
        if not sync_detail_width(self, "device-right"):
            return
        self.render_detail()

    def render_detail(self) -> None:
        from trace_core.tui.theme import detail_placeholder

        device = self._selected()
        if device is None:
            self.query_one(f"#{DEVICE_DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._items), "No devices visible to this adapter.")
            )
            return
        body = Text()
        device_type = "Physical device" if device.requires_real_hardware_opt_in else "Image-backed device"
        capacity = format_bytes(device.size_bytes) if device.size_bytes is not None else "—"
        body.append(f"{sanitize_terminal(_display_name(device))}\n", style=THEME_TOKENS["accent"])
        body.append(f"{device_type} · {capacity}\n", style="dim")
        section_head(body, "DEVICE DETAILS")
        self._dossier_row(body, "Node", device.node)
        self._dossier_row(body, "Access", "Not confirmed" if device.requires_real_hardware_opt_in else "Confirmed")
        section_head(body, "IDENTITY")
        self._append_fingerprint(body, device)
        section_head(body, "LINKED CASES")
        cases = self._cases_for(device.node)
        if cases:
            for number in cases:
                body.append(f"  {sanitize_terminal(number)}  Current\n", style=THEME_HEX["value"])
        else:
            body.append("  No linked cases.\n", style="dim")
        section_head(body, "IMAGING")
        self._append_imaging(body, device.node)
        body.append(f"\nINSPECTION HISTORY · {len(self._history)}\n", style=THEME_TOKENS["accent"])
        self._append_history(body)
        if self._gate is not None and self._gate_node == device.node:
            section_head(body, "WRITE PROTECTION")
            self._append_gate(body)
        section_head(body, "AUDIT REFERENCES")
        self._append_audit_refs(body, device)
        self.query_one(f"#{DEVICE_DETAIL_ID}", Static).update(body)

    @staticmethod
    def _dossier_row(body: Text, label: str, value: str) -> None:
        kv_row(body, label, value, LABEL_MD)

    def _refresh_node(self, node: str) -> None:
        """Drop one node's cached cases and repaint. Every mutation that can change which
        cases a device is filed under ends here."""
        self._cases_cache.pop(node, None)
        self.render_detail()

    def _cases_for(self, node: str) -> list[str]:
        """Cases this device is filed under. Cached per node so a dossier repaint never
        hits the database."""
        if node in self._cases_cache:
            return self._cases_cache[node]
        from trace_core.devices.helpers import do_node_case_labels

        try:
            cases = do_node_case_labels(self._manager, node)
        except Exception:
            cases = []
        self._cases_cache[node] = cases
        return cases

    def _append_fingerprint(self, body: Text, device: DeviceInfoDto) -> None:
        inspection = self._inspected
        if inspection is not None and inspection.device.node == device.node:
            fingerprint = inspection.fingerprint
            serial = fingerprint.serial
            interface = fingerprint.interface.value
            adapter = fingerprint.source
            firmware = fingerprint.firmware or ""
            wwn = fingerprint.wwn or ""
            observed = format_india_datetime(inspection.inspected_at)
        else:
            serial = device.serial or ""
            interface = ""
            adapter = ""
            firmware = ""
            wwn = ""
            observed = ""
        self._dossier_row(body, "Serial", serial)
        self._dossier_row(body, "Interface", interface)
        self._dossier_row(body, "Adapter", adapter)
        if firmware:
            self._dossier_row(body, "Firmware", firmware)
        if wwn:
            self._dossier_row(body, "WWN", wwn)
        self._dossier_row(body, "Observed", observed)

    def _append_imaging(self, body: Text, node: str) -> None:
        from trace_core.imaging.service import ImagingService

        try:
            operations = [op for op in ImagingService(self._manager).list_recent(50) if op.source_node == node]
        except Exception:
            body.append("  Imaging records unavailable.\n", style="dim")
            return
        if not operations:
            body.append("  No imaging operations recorded.\n", style="dim")
            return
        for operation in operations[:2]:
            state = operation.state.value.replace("_", " ").title()
            copied = format_bytes(operation.copied_bytes) if operation.copied_bytes is not None else "—"
            digest = (operation.acquisition_sha256 or "")[:12]
            line = f"  {state} · {copied}"
            if digest:
                line += f" · SHA-256 {digest}…"
            body.append(f"{line}\n")
            self._dossier_row(body, "Operation", str(operation.id))

    def _append_gate(self, body: Text) -> None:
        gate = self._gate
        if gate is None:
            return
        verdict = {
            "READ_ONLY": "Software read-only",
            "WRITABLE": "Writable",
            "UNKNOWN": "Unknown",
        }.get(gate.verdict.value, gate.verdict.value.replace("_", " ").title())
        self._dossier_row(body, "Verdict", verdict)
        self._dossier_row(body, "Checked", format_india_datetime(gate.checked_at))
        platform = "simulated" if gate.platform == "fake" else gate.platform
        self._dossier_row(body, "Platform", f"{platform} / {gate.adapter_version}")
        if gate.unknown_cause:
            self._dossier_row(body, "Cause", gate.unknown_cause)
        section_head(body, "CHECK RESULTS")
        for check in gate.checks:
            body.append(f"  {sanitize_terminal(check.name):<20}", style="dim")
            body.append(f"{sanitize_terminal(check.result)}\n")
        self._dossier_row(body, "Hardware gate", "Not verified")

    def _append_history(self, body: Text) -> None:
        if not self._history:
            body.append("  No inspections recorded.\n", style="dim")
            return
        for row in self._history:
            action = "Read-only Checked" if row.verdict is not None else "Device Inspected"
            body.append(
                f"  {format_india_datetime(row.inspected_at)}  {action}  {sanitize_terminal(row.inspected_by)}\n"
            )

    def _append_audit_refs(self, body: Text, device: DeviceInfoDto) -> None:
        from trace_core.audit.dto import AuditFilterDto
        from trace_core.audit.service import AuditService

        inspection = self._inspected
        serial = (inspection.fingerprint.serial if inspection else "") or device.serial or ""
        if not serial:
            body.append("  No device serial recorded.\n", style="dim")
            return
        try:
            events = AuditService(self._manager).list_events(AuditFilterDto(device_serial=serial, limit=3))
        except Exception:
            body.append("  Audit references unavailable.\n", style="dim")
            return
        for event in events:
            body.append(f"  {event.action.value}  #{event.seq}\n", style="dim")

    def _selected_node(self) -> str | None:
        device = self._selected()
        return None if device is None else device.node

    def action_inspect(self) -> None:
        node = self._selected_node()
        if node is None:
            self.app.notify(SELECT_DEVICE_FIRST, severity="warning")
            return
        self._authorise(node, lambda allowed: self._do_inspect(node, allowed))

    def action_check(self) -> None:
        node = self._selected_node()
        if node is None:
            self.app.notify(SELECT_DEVICE_FIRST, severity="warning")
            return
        self._authorise(node, lambda allowed: self._do_check(node, allowed))

    def _authorise(self, node: str, then: Callable[[bool], None]) -> None:
        """Real hardware needs explicit consent, never an implied grant [D24], [D27]."""
        from trace_core.tui.forms import YesNoModal

        selected = self._selected()
        if selected is None or not selected.requires_real_hardware_opt_in:
            then(False)
            return
        self.app.push_screen(
            YesNoModal(_device_prompt("Real hardware. Allow access to ", node, "?")),
            lambda answer: then(bool(answer)) if answer else self.app.notify("Cancelled.", severity="warning"),
        )

    def _do_inspect(self, node: str, allow_real_hardware: bool) -> None:
        from trace_core.devices.helpers import do_inspect
        from trace_core.tui.actions import run_guarded

        def _run() -> str:
            inspection = do_inspect(self._manager, node, allow_real_hardware=allow_real_hardware)
            self._inspected = inspection
            self._refresh_node(node)
            return f"Recorded fingerprint for {sanitize_terminal(node)}."

        run_guarded(self, _run)

    def _do_check(self, node: str, allow_real_hardware: bool, acknowledge: bool = False) -> None:
        from trace_core.devices.helpers import do_check
        from trace_core.tui.actions import run_guarded

        def _run() -> str:
            check = do_check(
                self._manager,
                node,
                allow_real_hardware=allow_real_hardware,
                acknowledge_unverified_source=acknowledge,
            )
            self._gate = check
            self._gate_node = node
            self._refresh_node(node)
            if acknowledge and check.verdict.value == "UNKNOWN":
                return "Source is UNKNOWN - accepted unverified; the override is in the ledger."
            return f"Write protection: {check.verdict.value}."

        run_guarded(self, _run)

    def action_acknowledge(self) -> None:
        node = self._selected_node()
        if node is None:
            self.app.notify(SELECT_DEVICE_FIRST, severity="warning")
            return
        from trace_core.devices.helpers import OVERRIDE_TOKEN
        from trace_core.tui.forms import TextInputModal

        self.app.push_screen(
            TextInputModal(f"Accept an unverified source (type {OVERRIDE_TOKEN})", OVERRIDE_TOKEN, required=True),
            lambda value: self._do_acknowledged(node, value),
        )

    def _do_acknowledged(self, node: str, value: str | None) -> None:
        from trace_core.devices.helpers import OVERRIDE_TOKEN

        if value is None:
            return
        if value != OVERRIDE_TOKEN:
            self.app.notify(f"Type {OVERRIDE_TOKEN} exactly to accept an unverified source.", severity="warning")
            return
        self._authorise(node, lambda allowed: self._do_check(node, allowed, acknowledge=True))

    def action_kind(self) -> None:
        cycle = {"all": "file", "file": "os", "os": "all"}
        self._kind = cycle.get(self._kind, "all")
        self.refresh_data()

    def _open_cases(self, term: str) -> list[tuple[str, str]]:
        """Rows for the picker. Search is the service's, not the modal's, so it matches
        lead_examiner and notes too and is not capped at one page."""
        from trace_core.cases.dto import CaseFilterDto
        from trace_core.cases.service import CaseService

        listed = CaseService(self._manager).list_cases(
            CaseFilterDto(search=term or None, include_deleted=False, limit=MAX_PICKER_ROWS)
        )
        return [(c.number, c.title or "") for c in listed]

    def action_link(self) -> None:
        node = self._selected_node()
        if node is None:
            self.app.notify(SELECT_DEVICE_FIRST, severity="warning")
            return
        from trace_core.tui.forms import CasePicker

        try:
            if not self._open_cases(""):
                self.app.notify("No open case to file this device under.", severity="warning")
                return
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
            return
        self.app.push_screen(
            CasePicker(self._open_cases, title="File under case"),
            lambda number: self._linked(node, number),
        )

    def _linked(self, node: str, case_number: str | None) -> None:
        if not case_number:
            return
        from trace_core.devices.helpers import do_link

        def _run() -> str:
            from trace_core.tui.screens.cases import CasesView

            link = do_link(self._manager, node, case_number)
            self._refresh_node(node)
            for cases_view in self.app.query(CasesView):
                cases_view.drop_dossier(case_number)
            return f"Filed {sanitize_terminal(link.node)} under {link.case_number}."

        run_guarded(self, _run)

    def action_unlink(self) -> None:
        node = self._selected_node()
        if node is None:
            self.app.notify(SELECT_DEVICE_FIRST, severity="warning")
            return
        from trace_core.devices.helpers import do_node_links

        try:
            links = do_node_links(self._manager, node)
        except Exception:
            links = []
        if not links:
            self.app.notify(f"{sanitize_terminal(node)} is not filed under any case.", severity="warning")
            return
        case_number = links[0].case_number
        from trace_core.tui.forms import YesNoModal

        self.app.push_screen(
            YesNoModal(_device_prompt("Remove ", node, f" from {case_number}?")),
            lambda answer: self._unlinked(node, case_number, answer),
        )

    def _unlinked(self, node: str, case_number: str, answer: bool | None) -> None:
        if not answer:
            return
        from trace_core.devices.helpers import do_unlink

        def _run() -> str:
            from trace_core.tui.screens.cases import CasesView

            do_unlink(self._manager, node, case_number)
            self._refresh_node(node)
            for cases_view in self.app.query(CasesView):
                cases_view.drop_dossier(case_number)
            return f"Removed {sanitize_terminal(node)} from {case_number}."

        run_guarded(self, _run)

    def run_command(self, command: str) -> None:
        action = command.removeprefix("device-")
        if action == "inspect":
            self.action_inspect()
        elif action == "check":
            self.action_check()
        elif action == "history":
            self._show_history()
        elif action == "link":
            self.action_link()
        elif action == "unlink":
            self.action_unlink()
        elif action == "export":
            self.action_export()
        else:
            unknown_command(self, command)

    def _show_history(self) -> None:
        """Every prior observation of the selected device, newest first."""
        node = self._selected_node()
        if node is None:
            self.app.notify(SELECT_DEVICE_FIRST, severity="warning")
            return
        serial = self._history_key(node)
        if not serial:
            return

        from trace_core.devices.helpers import do_history

        def _history() -> str:
            rows = do_history(self._manager, serial, 50)
            self._history = rows
            self.render_detail()
            return f"{len(rows)} observation(s) for {sanitize_terminal(node)}."

        run_guarded(self, _history)

    def _history_key(self, node: str) -> str:
        """History is keyed by serial, which the listing now carries.

        The current session's inspection is authoritative; otherwise the serial the
        device list already shows is used, so history is reachable without inspecting.
        A device never seen before has no history yet.
        """
        inspection = self._inspected
        if inspection is not None and inspection.device.node == node:
            return inspection.fingerprint.serial
        serial = self._serials.get(node)
        if serial:
            return serial
        self.app.notify(
            f"No recorded observation for {sanitize_terminal(node)} yet. Press i to inspect it.",
            severity="warning",
        )
        return ""

    def action_export(self) -> None:
        from trace_core.tui.forms import TextInputModal

        self.app.push_screen(TextInputModal("Export device observations to", "devices.jsonl"), self._exported)

    def _exported(self, path: str | None) -> None:
        if not path:
            return
        confirm_overwrite(self, path, lambda: self._do_export(path))

    def _do_export(self, path: str) -> None:
        from trace_core.core.database.session import db_manager
        from trace_core.devices.exporter import export_observations

        def _export() -> str:
            with db_manager.session() as session:
                out = export_observations(session, path)
            return f"Exported device observations to {out}."

        run_guarded(self, _export)

    def focus_default(self) -> None:
        self._table().focus()

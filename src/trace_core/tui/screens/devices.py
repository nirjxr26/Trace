"""Devices tab: enumeration, fingerprint detail, and the write-protection gate.

Every service call goes through the same `helpers.do_*` cores the Typer CLI and the
REPL use, so the three surfaces cannot drift. Hardware strings are attacker-controlled
bytes, so every value reaching the terminal goes through `sanitize_terminal`.
"""

from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.timer import Timer
from textual.widgets import DataTable, Input, Rule, Static

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import format_india_datetime, sanitize_terminal
from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
from trace_core.devices.dto import DeviceInfoDto, InspectionDto, ObservationDto, WpCheckDto
from trace_core.devices.renderers import display_node, format_bytes, readable_model, verdict_style
from trace_core.tui.actions import confirm_overwrite, run_guarded
from trace_core.tui.widgets import DossierScroll, TablePane, active_tab

TABLE_ID = "device-table"
DEVICE_HEADER_ID = "device-header"
DEVICE_DETAIL_ID = "device-detail"
DEVICE_SUMMARY_ID = "device-summary"
TABLE_COLUMNS = (("Device", 15), ("Size", 9))
MAX_PICKER_ROWS = 200
POLL_SECONDS = 1.0
SELECT_DEVICE_FIRST = "Select a device first."


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
        self._cases_cache: dict[str, list[str]] = {}
        self._serials: dict[str, str] = {}
        self._history: list[ObservationDto] = []
        self._detail_width: int | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self._last_token: tuple[str, ...] | None = None
        self._refresh_timer = self.set_interval(POLL_SECONDS, self._poll_devices)

    def on_unmount(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="device-main"):
            with Vertical(id="device-left"):
                yield Input(placeholder="Search node or model...", id="device-search")
                yield Static("", id=DEVICE_SUMMARY_ID, classes="muted")
                yield Static("", id=DEVICE_HEADER_ID, classes="table-head")
                yield Rule()
                yield DataTable(id=TABLE_ID, cursor_type="row", show_header=False)
            with DossierScroll(id="device-right"):
                yield Static("Select a device…", id=DEVICE_DETAIL_ID)

    def refresh_data(self) -> None:
        devices = self._fetch()
        if devices is None:
            return
        self._last_token = self._token()
        self._render_list(devices)

    def _poll_devices(self) -> None:
        if active_tab(self) != "devices":
            return
        token = self._token()
        if token is not None and token == self._last_token:
            return
        devices = self._fetch(quiet=True)
        if devices is not None:
            self._last_token = token
            self._render_list(devices)

    def _token(self) -> tuple[str, ...] | None:
        from trace_core.devices.helpers import do_change_token

        try:
            return do_change_token(self._manager)
        except Exception:
            return None

    def _fetch(self, quiet: bool = False) -> list[DeviceInfoDto] | None:
        from trace_core.devices.helpers import do_list

        try:
            devices = do_list(self._manager, self._kind)
        except Exception as exc:  # boundary: a service failure becomes a toast, never a crash
            if not quiet:
                self.app.notify(str(exc), severity="error")
            return None
        self._serials = {d.node: d.serial for d in devices if d.serial}
        query = self.query_one("#device-search", Input).value.strip() or None
        if query:
            devices = [
                d
                for d in devices
                if query in d.node.lower() or query in (d.model_hint or "").lower() or query in (d.serial or "").lower()
            ]
        return devices

    def _render_list(self, devices: list[DeviceInfoDto]) -> None:
        summary = self.query_one(f"#{DEVICE_SUMMARY_ID}", Static)
        summary.update(f"kind: {self._kind}")
        self.fill_table(devices, [d.node for d in devices])

    def row_cells(self, device: DeviceInfoDto, selected: bool) -> list:  # type: ignore[no-untyped-def]
        from trace_core.core.ui.renderers import fit_text
        from trace_core.tui.theme import SELECT_PREFIX

        prefix = SELECT_PREFIX if selected else "  "
        width = TABLE_COLUMNS[0][1] - len(prefix)
        name = fit_text(sanitize_terminal(_display_name(device)), width)
        return [f"{prefix}{name}", format_bytes(device.size_bytes)]

    def on_resize(self, event: Resize) -> None:
        """Dividers are baked for one width; rebuild them when the width moves."""
        width = self.query_one("#device-right", DossierScroll).content_region.width
        if width == self._detail_width:
            return
        self._detail_width = width
        self.render_detail()

    def render_detail(self) -> None:
        from trace_core.tui.theme import detail_placeholder

        device = self._selected()
        if device is None:
            self.query_one(f"#{DEVICE_DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._items), "No devices visible to this adapter.")
            )
            return
        pane = self.query_one("#device-right", DossierScroll)
        body = Text()
        body.append(f"{sanitize_terminal(_display_name(device))}\n", style=THEME_TOKENS["accent"])
        body.append(pane.divider())
        body.append("\n")
        body.append("Node       ", style="dim")
        body.append(f"{sanitize_terminal(device.node)}\n")
        body.append("Kind       ", style="dim")
        body.append(f"{device.kind.value}\n")
        body.append("Size       ", style="dim")
        body.append(f"{sanitize_terminal(format_bytes(device.size_bytes))}\n")
        body.append("Model      ", style="dim")
        body.append(f"{sanitize_terminal(device.model_hint or '-')}\n")
        body.append("Hardware   ", style="dim")
        body.append(
            "real device - access needs confirming\n"
            if device.requires_real_hardware_opt_in
            else "emulated or image-backed\n"
        )
        if self._inspected is not None and self._inspected.device.node == device.node:
            body.append(pane.divider())
            body.append("\nIDENTITY\n", style=THEME_TOKENS["accent"])
            self._append_fingerprint(body)
        self._append_cases(body, pane, device.node)
        self._append_history(body, pane)
        if self._gate is not None and self._gate_node == device.node:
            body.append(pane.divider())
            body.append("\nWRITE PROTECTION\n", style=THEME_TOKENS["accent"])
            self._append_gate(body)
        self.query_one(f"#{DEVICE_DETAIL_ID}", Static).update(body)

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

    def _append_fingerprint(self, body: Text) -> None:
        inspection = self._inspected
        if inspection is None:
            return
        fingerprint = inspection.fingerprint
        body.append("Serial     ", style="dim")
        body.append(f"{sanitize_terminal(fingerprint.serial)}\n")
        body.append("Interface  ", style="dim")
        body.append(f"{fingerprint.interface.value}\n")
        body.append("Source     ", style="dim")
        body.append(f"{fingerprint.source}\n")
        body.append("Firmware   ", style="dim")
        body.append(f"{sanitize_terminal(fingerprint.firmware or '-')}\n")
        body.append("WWN        ", style="dim")
        body.append(f"{sanitize_terminal(fingerprint.wwn or '-')}\n")
        body.append("Observed   ", style="dim")
        body.append(f"{format_india_datetime(inspection.inspected_at)}\n")

    def _append_gate(self, body: Text) -> None:
        gate = self._gate
        if gate is None:
            return
        _, style = verdict_style(gate.verdict.value)
        body.append("Verdict    ", style="dim")
        body.append(f"{gate.verdict.value}\n", style=style)
        if gate.unknown_cause:
            body.append("Cause      ", style="dim")
            body.append(f"{sanitize_terminal(gate.unknown_cause)}\n")
        body.append("Timestamp  ", style="dim")
        body.append(f"{format_india_datetime(gate.checked_at)}\n")
        body.append("Platform   ", style="dim")
        source = "simulated" if gate.platform == "fake" else gate.platform
        body.append(f"{sanitize_terminal(source)} / {sanitize_terminal(gate.adapter_version)}\n")
        body.append("\nEvidence\n")
        for check in gate.checks:
            body.append(f"  {sanitize_terminal(check.name):<18}", style="dim")
            body.append(f"{sanitize_terminal(check.result)}")
            if check.detail:
                body.append(f"  {sanitize_terminal(check.detail)}")
            body.append("\n")

    def _append_cases(self, body: Text, pane: DossierScroll, node: str) -> None:
        cases = self._cases_for(node)
        if not cases:
            return
        body.append(pane.divider())
        body.append("\nCASES\n", style=THEME_TOKENS["accent"])
        for number in cases:
            body.append(f"  {sanitize_terminal(number)}\n", style=THEME_HEX["value"])

    def _append_history(self, body: Text, pane: DossierScroll) -> None:
        if not self._history:
            return
        body.append(pane.divider())
        body.append(f"\nHISTORY · {len(self._history)}\n", style=THEME_TOKENS["accent"])
        for row in self._history:
            verdict = row.verdict.value if row.verdict else "-"
            body.append(
                f"  {format_india_datetime(row.inspected_at)}  {sanitize_terminal(verdict)}"
                f"  {sanitize_terminal(row.inspected_by)}\n"
            )

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
            YesNoModal(f"Real hardware. Allow access to {sanitize_terminal(node)}?"),
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
            self.app.notify("Select a device first.", severity="warning")
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
            YesNoModal(f"Remove {sanitize_terminal(node)} from {case_number}?"),
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
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

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

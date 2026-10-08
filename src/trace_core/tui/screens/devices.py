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
from textual.timer import Timer
from textual.widgets import DataTable, Input, Rule, Static

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import format_india_datetime, sanitize_terminal
from trace_core.core.ui.theme import THEME_TOKENS
from trace_core.devices.dto import DeviceInfoDto, InspectionDto, WpCheckDto
from trace_core.devices.renderers import format_bytes, verdict_style
from trace_core.tui.widgets import DossierScroll, TablePane

TABLE_ID = "device-table"
DEVICE_HEADER_ID = "device-header"
DEVICE_DETAIL_ID = "device-detail"
DEVICE_SUMMARY_ID = "device-summary"
TABLE_COLUMNS = (("Device", 24), ("Size", 11))
POLL_SECONDS = 1.0


def _display_name(device: DeviceInfoDto) -> str:
    """Human name first, node basename when the adapter knows nothing friendlier."""
    if device.model_hint:
        return device.model_hint
    return device.node.replace("\\", "/").rsplit("/", 1)[-1] or device.node


class DevicesView(TablePane[DeviceInfoDto]):
    """Left: enumerated devices. Right: fingerprint, then the write-protection gate."""

    BINDINGS = [
        Binding("i", "inspect", "Inspect"),
        Binding("c", "check", "Check"),
        Binding("k", "kind", "Kind"),
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
                yield Rule()
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
        query = self.query_one("#device-search", Input).value.strip() or None
        if query:
            devices = [d for d in devices if query in d.node.lower() or query in (d.model_hint or "").lower()]
        return devices

    def _render_list(self, devices: list[DeviceInfoDto]) -> None:
        summary = self.query_one(f"#{DEVICE_SUMMARY_ID}", Static)
        summary.update(f"{len(devices)} device(s) · kind: {self._kind}")
        self.fill_table(devices, [d.node for d in devices])

    def row_cells(self, device: DeviceInfoDto, selected: bool) -> list:  # type: ignore[no-untyped-def]
        from trace_core.tui.theme import SELECT_PREFIX

        prefix = SELECT_PREFIX if selected else "  "
        return [f"{prefix}{sanitize_terminal(_display_name(device))}", format_bytes(device.size_bytes)]

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
        body.append(f"{sanitize_terminal(device.node)}\n", style=THEME_TOKENS["accent"])
        body.append(pane.divider())
        body.append("\n")
        body.append("Kind       ", style="dim")
        body.append(f"{device.kind.value}\n")
        body.append("Size       ", style="dim")
        body.append(f"{sanitize_terminal(format_bytes(device.size_bytes))}\n")
        body.append("Model      ", style="dim")
        body.append(f"{sanitize_terminal(device.model_hint or '-')}\n")
        body.append("Real HW    ", style="dim")
        body.append("yes - requires --allow-real-hardware\n" if device.requires_real_hardware_opt_in else "no\n")
        if self._inspected is not None and self._inspected.device.node == device.node:
            body.append(pane.divider())
            body.append("\nFINGERPRINT\n")
            self._append_fingerprint(body)
        if self._gate is not None and self._gate_node == device.node:
            body.append(pane.divider())
            body.append("\nWRITE PROTECTION\n")
            self._append_gate(body)
        self.query_one(f"#{DEVICE_DETAIL_ID}", Static).update(body)

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
        body.append("When       ", style="dim")
        body.append(f"{format_india_datetime(gate.checked_at)}\n")
        body.append("Platform   ", style="dim")
        body.append(f"{sanitize_terminal(gate.platform)} / {sanitize_terminal(gate.adapter_version)}\n")
        body.append("\nEvidence\n")
        for check in gate.checks:
            body.append(f"  {sanitize_terminal(check.name):<18}", style="dim")
            body.append(f"{sanitize_terminal(check.result)}")
            if check.detail:
                body.append(f"  {sanitize_terminal(check.detail)}")
            body.append("\n")

    def _selected_node(self) -> str | None:
        device = self._selected()
        return None if device is None else device.node

    def action_inspect(self) -> None:
        node = self._selected_node()
        if node is None:
            self.app.notify("Select a device first.", severity="warning")
            return
        self._authorise(node, lambda allowed: self._do_inspect(node, allowed))

    def action_check(self) -> None:
        node = self._selected_node()
        if node is None:
            self.app.notify("Select a device first.", severity="warning")
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
            self.render_detail()
            return f"Recorded fingerprint for {sanitize_terminal(node)}."

        run_guarded(self, _run)

    def _do_check(self, node: str, allow_real_hardware: bool) -> None:
        from trace_core.devices.helpers import do_check
        from trace_core.tui.actions import run_guarded

        def _run() -> str:
            check = do_check(self._manager, node, allow_real_hardware=allow_real_hardware)
            self._gate = check
            self._gate_node = node
            self.render_detail()
            return f"Write protection: {check.verdict.value}."

        run_guarded(self, _run)

    def action_kind(self) -> None:
        cycle = {"all": "file", "file": "os", "os": "all"}
        self._kind = cycle.get(self._kind, "all")
        self.refresh_data()

    def run_command(self, command: str) -> None:
        action = command.removeprefix("device-")
        if action == "inspect":
            self.action_inspect()
        elif action == "check":
            self.action_check()
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

    def focus_default(self) -> None:
        self._table().focus()

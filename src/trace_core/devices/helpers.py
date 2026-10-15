"""Device operation cores shared by the Typer CLI and the REPL shell.

One implementation each, called from both. The CLI keeps its error cards and exit codes;
the shell keeps its flow. Neither re-implements the other, and neither re-derives
validation the service already performs.
"""

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.devices.domain import ObservedDevice
from trace_core.devices.dto import (
    CaseDeviceLinkDto,
    DeviceInfoDto,
    InspectionDto,
    ObservationDto,
    WpCheckDto,
)
from trace_core.devices.service import KIND_ALL, DeviceService


def _service(session_manager: DatabaseSessionManager | None = None) -> DeviceService:
    return DeviceService(session_manager)


def do_list(
    session_manager: DatabaseSessionManager | None,
    kind: str = KIND_ALL,
    *,
    audit_recognition: bool = False,
) -> list[DeviceInfoDto]:
    """Discovery only: no persistence, no evidentiary read [D10], [D23]. Audited only
    when the caller asks: explicit CLI/REPL lists pass `audit_recognition`, while the
    TUI refresh and tab-completion stay silent.

    What was previously observed for the same node is carried along so `device history`
    is usable without inspecting first, and so a listed device can be described; that
    read is separate and touches no device."""
    service = _service(session_manager)
    devices = service.list_devices(kind, audit_recognition=audit_recognition)
    observed = service.observed_devices()
    return [
        DeviceInfoDto.from_domain(device, observed[device.node].serial if device.node in observed else None)
        for device in devices
    ]


def do_observed_devices(session_manager: DatabaseSessionManager | None) -> dict[str, ObservedDevice]:
    """Newest recorded identity per node, keyed by node. Backs the case dossier."""
    return _service(session_manager).observed_devices()


def do_change_token(session_manager: DatabaseSessionManager | None) -> tuple[str, ...]:
    return _service(session_manager).change_token()


def do_inspect(
    session_manager: DatabaseSessionManager | None,
    node: str,
    *,
    allow_real_hardware: bool = False,
) -> InspectionDto:
    inspection = _service(session_manager).inspect_device(node, allow_real_hardware=allow_real_hardware)
    return InspectionDto.from_domain(inspection)


def do_link(
    session_manager: DatabaseSessionManager | None,
    node: str,
    case_number: str,
    *,
    label: str | None = None,
) -> CaseDeviceLinkDto:
    return CaseDeviceLinkDto.from_domain(_service(session_manager).link_device(node, case_number, label=label))


def do_unlink(session_manager: DatabaseSessionManager | None, node: str, case_number: str) -> None:
    _service(session_manager).unlink_device(node, case_number)


def do_case_links(
    session_manager: DatabaseSessionManager | None,
    case_number: str,
    limit: int = 100,
) -> list[CaseDeviceLinkDto]:
    return [CaseDeviceLinkDto.from_domain(o) for o in _service(session_manager).links_for_case(case_number, limit)]


def do_case_device_rows(
    session_manager: DatabaseSessionManager | None, case_number: str
) -> list[dict[str, object]] | None:
    """Devices ever filed under one case for the CLI dossier. Mirrors the TUI record:
    current links plus ledger-surviving history, headings from the newest observation.

    Returns None (with a dim notice, like `fetch_case_with_history`) when the links or
    the ledger cannot be read — unreadable is not the same as no devices.
    """
    import json

    from trace_core.audit.domain import AuditAction
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.core.errors import ApplicationError
    from trace_core.core.ui.renderers import console
    from trace_core.devices.renderers import device_heading

    try:
        current = do_case_links(session_manager, case_number)
        observed = do_observed_devices(session_manager)
        history: dict[str, None] = {}
        for event in AuditService(session_manager).list_events(
            AuditFilterDto(case_number=case_number, action=AuditAction.DEVICE_LINKED, limit=500)
        ):
            try:
                node = json.loads(event.payload_json).get("details", {}).get("node")
            except (TypeError, ValueError):
                continue
            if node:
                history.setdefault(str(node))
    except ApplicationError as exc:
        console.print(f"[dim]Filed devices unavailable — {exc}[/dim]\n")
        return None

    def _row(node: str, label: str, is_current: bool) -> dict[str, object]:
        record = observed.get(node)
        model = record.model if record is not None and record.model else ""
        capacity = record.capacity_bytes if record is not None else None
        return {
            "node": node,
            "label": label,
            "heading": device_heading(node, model or None, capacity),
            "current": is_current,
        }

    rows = [_row(link.node, link.label or "", True) for link in current]
    linked_now = {row["node"] for row in rows}
    rows.extend(_row(node, "", False) for node in history if node not in linked_now)
    return rows


def do_node_case_numbers(session_manager: DatabaseSessionManager | None, node: str) -> list[str] | None:
    """Cases one device is filed under, for the CLI inspection card. None (with a dim
    notice) when the links cannot be read — unreadable is not the same as unfiled."""
    from trace_core.core.errors import ApplicationError
    from trace_core.core.ui.renderers import console

    try:
        return [link.case_number for link in do_node_links(session_manager, node)]
    except ApplicationError as exc:
        console.print(f"[dim]Filed cases unavailable — {exc}[/dim]\n")
        return None


def do_node_links(session_manager: DatabaseSessionManager | None, node: str) -> list[CaseDeviceLinkDto]:
    return [CaseDeviceLinkDto.from_domain(o) for o in _service(session_manager).links_for_node(node)]


def do_check(
    session_manager: DatabaseSessionManager | None,
    node: str,
    *,
    allow_real_hardware: bool = False,
    acknowledge_unverified_source: bool = False,
    override_reason: str = "",
) -> WpCheckDto:
    """Run the gate. Raises `WriteProtectionError` carrying verdict and evidence on refusal."""
    gate = _service(session_manager).check_device(
        node,
        allow_real_hardware=allow_real_hardware,
        acknowledge_unverified_source=acknowledge_unverified_source,
        override_reason=override_reason,
    )
    return WpCheckDto.from_domain(gate)


def do_history(
    session_manager: DatabaseSessionManager | None,
    serial: str,
    limit: int = 10,
) -> list[ObservationDto]:
    """Prior observations of one identity, newest first."""
    return [ObservationDto.from_domain(o) for o in _service(session_manager).observation_history(serial, limit)]

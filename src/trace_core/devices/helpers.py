"""Device operation cores shared by the Typer CLI and the REPL shell.

One implementation each, called from both. The CLI keeps its error cards and exit codes;
the shell keeps its flow. Neither re-implements the other, and neither re-derives
validation the service already performs.
"""

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.devices.dto import DeviceInfoDto, InspectionDto, WpCheckDto
from trace_core.devices.service import KIND_ALL, DeviceService


def _service(session_manager: DatabaseSessionManager | None = None) -> DeviceService:
    return DeviceService(session_manager)


def do_list(
    session_manager: DatabaseSessionManager | None,
    kind: str = KIND_ALL,
) -> list[DeviceInfoDto]:
    """Discovery only: no persistence, no audit, no evidentiary read [D10], [D23]."""
    return [DeviceInfoDto.from_domain(device) for device in _service(session_manager).list_devices(kind)]


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


def do_check(
    session_manager: DatabaseSessionManager | None,
    node: str,
    *,
    allow_real_hardware: bool = False,
    acknowledge_unverified_source: bool = False,
) -> WpCheckDto:
    """Run the gate. Raises `WriteProtectionError` carrying verdict and evidence on refusal."""
    gate = _service(session_manager).check_device(
        node,
        allow_real_hardware=allow_real_hardware,
        acknowledge_unverified_source=acknowledge_unverified_source,
    )
    return WpCheckDto.from_domain(gate)

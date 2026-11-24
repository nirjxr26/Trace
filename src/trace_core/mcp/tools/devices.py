from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from trace_core.devices.dto import CaseDeviceLinkDto, DeviceInfoDto, ObservationDto
from trace_core.devices.service import DeviceService
from trace_core.mcp.constants import (
    TOOL_DEVICE_HISTORY,
    TOOL_DEVICE_LINK,
    TOOL_DEVICE_LINKS,
    TOOL_DEVICE_LIST,
    TOOL_DEVICE_OBSERVED,
    TOOL_DEVICE_UNLINK,
)
from trace_core.mcp.errors import ToolFailure
from trace_core.mcp.schemas import DeviceMutationArgs, checked
from trace_core.mcp.serialize import to_result
from trace_core.mcp.server import ServerContext, execute, mcp_tool
from trace_core.mcp.tools import OPEN_WORLD_READ, READ_ONLY, WRITE

Kind = Annotated[str, Field(pattern="^(all|FILE|OS)$")]
Serial = Annotated[str, Field(min_length=1, max_length=255)]
Node = Annotated[str, Field(min_length=1, max_length=4096)]
HistoryLimit = Annotated[int, Field(ge=1, le=50)]
LinkLimit = Annotated[int, Field(ge=1, le=100)]


def register(server: MCPServer, ctx: ServerContext) -> None:
    @mcp_tool(
        server,
        TOOL_DEVICE_LIST,
        annotations=OPEN_WORLD_READ,
        description="Enumerate visible devices without reading or writing them.",
    )
    def trace_device_list(kind: Kind = "all") -> dict:
        return execute(ctx, TOOL_DEVICE_LIST, lambda: _list(ctx, kind))

    @mcp_tool(
        server,
        TOOL_DEVICE_OBSERVED,
        annotations=READ_ONLY,
        description="List newest stored observations per device node.",
    )
    def trace_device_observed() -> dict:
        return execute(ctx, TOOL_DEVICE_OBSERVED, lambda: _observed(ctx))

    @mcp_tool(
        server,
        TOOL_DEVICE_HISTORY,
        annotations=READ_ONLY,
        description="List observation history for one serial number.",
    )
    def trace_device_history(serial: Serial, limit: HistoryLimit = 10) -> dict:
        return execute(ctx, TOOL_DEVICE_HISTORY, lambda: _history(ctx, serial, limit))

    @mcp_tool(
        server,
        TOOL_DEVICE_LINKS,
        annotations=READ_ONLY,
        description="List case/device links by case number or device node.",
    )
    def trace_device_links(
        case_number: Serial | None = None,
        node: Node | None = None,
        limit: LinkLimit = 100,
    ) -> dict:
        return execute(ctx, TOOL_DEVICE_LINKS, lambda: _links(ctx, case_number, node, limit))

    @mcp_tool(
        server,
        TOOL_DEVICE_LINK,
        annotations=WRITE,
        description="File a device node under a case. Confirm by repeating the case number.",
    )
    def trace_device_link(
        node: Node, case_number: Serial, label: Serial | None = None, confirm: Serial | None = None
    ) -> dict:
        return execute(ctx, TOOL_DEVICE_LINK, lambda: _link(ctx, node, case_number, label, confirm))

    @mcp_tool(
        server,
        TOOL_DEVICE_UNLINK,
        annotations=WRITE,
        description="Remove a device node from a case. Confirm by repeating the case number.",
    )
    def trace_device_unlink(node: Node, case_number: Serial, confirm: Serial | None = None) -> dict:
        return execute(ctx, TOOL_DEVICE_UNLINK, lambda: _unlink(ctx, node, case_number, confirm))


def _list(ctx: ServerContext, kind: str) -> dict:
    devices = DeviceService(ctx.session_manager).list_devices(kind=kind, audit_recognition=False)
    return to_result([DeviceInfoDto.from_domain(device).model_dump(mode="json") for device in devices])


def _observed(ctx: ServerContext) -> dict:
    observed = DeviceService(ctx.session_manager).observed_devices()
    return to_result(
        {
            node: {
                "serial": record.serial,
                "model": record.model,
                "capacity_bytes": record.capacity_bytes,
            }
            for node, record in observed.items()
        }
    )


def _history(ctx: ServerContext, serial: str, limit: int) -> dict:
    rows = DeviceService(ctx.session_manager).observation_history(serial, limit)
    return to_result([ObservationDto.from_domain(row).model_dump(mode="json") for row in rows])


def _links(ctx: ServerContext, case_number: str | None, node: str | None, limit: int) -> dict:
    if (case_number is None) == (node is None):
        raise ToolFailure("VALIDATION", "Provide exactly one of case_number or node.")
    service = DeviceService(ctx.session_manager)
    if case_number is not None:
        links = service.links_for_case(case_number, limit)
    else:
        assert node is not None
        links = service.links_for_node(node)[:limit]
    return to_result([CaseDeviceLinkDto.from_domain(link).model_dump(mode="json") for link in links])


def _link(ctx: ServerContext, node: str, case_number: str, label: str | None, confirm: str | None) -> dict:
    checked(
        DeviceMutationArgs,
        {"node": node, "case_number": case_number, "label": label, "confirm": confirm},
    )
    link = DeviceService(ctx.session_manager).link_device(node, case_number, label=label)
    return to_result(CaseDeviceLinkDto.from_domain(link).model_dump(mode="json"))


def _unlink(ctx: ServerContext, node: str, case_number: str, confirm: str | None) -> dict:
    checked(DeviceMutationArgs, {"node": node, "case_number": case_number, "confirm": confirm})
    DeviceService(ctx.session_manager).unlink_device(node, case_number)
    return to_result({"node": node, "case_number": case_number, "unlinked": True})

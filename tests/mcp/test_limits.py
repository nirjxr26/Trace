import pytest
from conftest import ClientHarness  # type: ignore[import-not-found]

from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.devices.service import DeviceService
from trace_core.mcp import MAX_RESPONSE_BYTES
from trace_core.mcp.errors import ToolFailure
from trace_core.mcp.serialize import size_guard


def test_pagination_bounds_through_mcp(mcp_manager: DatabaseSessionManager, mcp_client: ClientHarness) -> None:
    for index in range(3):
        CaseService(mcp_manager).create_case(CaseCreateDto(title=f"Limit case {index}", lead_examiner="Analyst"))

    for limit in (0, 201):
        response = mcp_client.call("trace_case_list", {"limit": limit})
        assert response.is_error is True

    response = mcp_client.call("trace_case_list", {"limit": 2})
    assert response.is_error is False
    payload = response.structured_content
    assert len(payload["items"]) == 2
    assert payload["pagination"]["limit"] == 2


def test_audit_pagination_bounds_through_mcp(mcp_client: ClientHarness) -> None:
    response = mcp_client.call("trace_audit_list", {"limit": 0})
    assert response.is_error is True
    response = mcp_client.call("trace_audit_list", {"limit": 201})
    assert response.is_error is True


def test_recent_respects_caller_pagination(mcp_manager: DatabaseSessionManager, mcp_client: ClientHarness) -> None:
    for index in range(8):
        CaseService(mcp_manager).create_case(CaseCreateDto(title=f"Recent case {index}", lead_examiner="Analyst"))

    response = mcp_client.call("trace_case_list", {"recent": True, "limit": 3})
    assert response.is_error is False
    payload = response.structured_content
    assert len(payload["items"]) == 3
    assert payload["pagination"] == {"limit": 3, "offset": 0, "returned": 3}


def test_device_links_node_honors_limit(mcp_manager: DatabaseSessionManager, mcp_client: ClientHarness) -> None:
    CaseService(mcp_manager).create_case(CaseCreateDto(title="Links case", lead_examiner="Analyst"))
    service = DeviceService(mcp_manager)
    for index in range(4):
        service.link_device(f"/dev/fake{index}", "2026-CR-0001")

    response = mcp_client.call("trace_device_links", {"node": "/dev/fake0", "limit": 1})
    assert response.is_error is False
    assert len(response.structured_content["items"]) == 1


def test_size_guard_rejects_oversized_payload() -> None:
    with pytest.raises(ToolFailure) as caught:
        size_guard({"data": "x" * (MAX_RESPONSE_BYTES + 1)})
    assert caught.value.code == "RESPONSE_TOO_LARGE"

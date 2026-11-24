from datetime import datetime
from pathlib import Path

from conftest import ClientHarness  # type: ignore[import-not-found]

from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager


def test_status_reports_sanitized_identity(mcp_client: ClientHarness) -> None:
    response = mcp_client.call("trace_status")
    assert response.is_error is False
    payload = response.structured_content
    assert payload["transport"] == "stdio"
    assert payload["protocol_version"] == "2026-07-28"
    assert payload["database"]["healthy"] is True
    assert "password" not in payload["database"]["identity"]


def test_case_get_and_list(mcp_manager: DatabaseSessionManager, mcp_client: ClientHarness) -> None:
    created = CaseService(mcp_manager).create_case(CaseCreateDto(title="Evidence", lead_examiner="Analyst"))
    fetched = mcp_client.call("trace_case_get", {"identifier": created.number})
    assert fetched.is_error is False
    assert fetched.structured_content["number"] == created.number
    listed = mcp_client.call("trace_case_list", {"limit": 10})
    assert listed.is_error is False
    assert listed.structured_content["pagination"]["returned"] >= 1
    opened_at = datetime.fromisoformat(fetched.structured_content["opened_at"])
    assert opened_at.tzinfo is not None


def test_audit_verify_and_get(mcp_client: ClientHarness) -> None:
    verified = mcp_client.call("trace_audit_verify")
    assert verified.is_error is False
    assert verified.structured_content["is_valid"] is True
    listed = mcp_client.call("trace_audit_list", {"limit": 5})
    assert listed.is_error is False
    if listed.structured_content["items"]:
        seq = listed.structured_content["items"][0]["seq"]
        event = mcp_client.call("trace_audit_get", {"seq": seq})
        assert event.is_error is False
        assert isinstance(event.structured_content["payload_json"], str)


def test_device_list_does_not_write(
    mcp_manager: DatabaseSessionManager, mcp_client: ClientHarness, device_file_env: object
) -> None:
    before = AuditService(mcp_manager).head()
    response = mcp_client.call("trace_device_list", {"kind": "all"})
    after = AuditService(mcp_manager).head()
    assert response.is_error is False
    assert before == after


def test_extra_arguments_are_rejected(mcp_client: ClientHarness) -> None:
    response = mcp_client.call("trace_case_list", {"limit": 5, "actor": "admin"})
    assert response.is_error is True
    assert "extra_forbidden" in response.content[0].text


def test_missing_operator_is_denied(tmp_path: Path) -> None:
    from conftest import ClientHarness  # type: ignore[import-not-found]

    from trace_core.mcp.server import build_server

    mgr = DatabaseSessionManager(f"sqlite:///{tmp_path / 'empty.db'}")
    mgr.init_schema()
    harness = ClientHarness(build_server(mgr))
    response = harness.call("trace_status")
    assert response.is_error is True
    assert "FORBIDDEN" in response.content[0].text

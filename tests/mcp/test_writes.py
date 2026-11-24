import json

from conftest import ClientHarness  # type: ignore[import-not-found]

from trace_core.core.database.session import DatabaseSessionManager


def test_case_lifecycle_through_mcp(mcp_manager: DatabaseSessionManager, mcp_client: ClientHarness) -> None:
    created = mcp_client.call("trace_case_create", {"title": "MCP case", "lead_examiner": "Analyst"})
    assert created.is_error is False
    number = created.structured_content["number"]

    updated = mcp_client.call("trace_case_update", {"identifier": number, "title": "MCP case edited"})
    assert updated.is_error is False
    assert updated.structured_content["title"] == "MCP case edited"

    reviewed = mcp_client.call("trace_case_review", {"identifier": number})
    assert reviewed.is_error is False
    assert reviewed.structured_content["status"] == "UNDER_REVIEW"

    closed = mcp_client.call("trace_case_close", {"identifier": number, "reason": "sealed", "confirm": number})
    assert closed.is_error is False
    assert closed.structured_content["status"] == "CLOSED"

    blocked = mcp_client.call("trace_case_update", {"identifier": number, "title": "again"})
    assert blocked.is_error is True
    reopened = mcp_client.call("trace_case_review", {"identifier": number})
    assert reopened.is_error is True
    assert "INVALID_STATE" in reopened.content[0].text


def test_confirmation_mismatch_prevents_close(mcp_client: ClientHarness) -> None:
    created = mcp_client.call("trace_case_create", {"title": "Confirm", "lead_examiner": "Analyst"})
    number = created.structured_content["number"]
    response = mcp_client.call(
        "trace_case_close", {"identifier": number, "reason": "sealed", "confirm": "wrong-number"}
    )
    assert response.is_error is True
    assert "VALIDATION" in response.content[0].text
    fetched = mcp_client.call("trace_case_get", {"identifier": number})
    assert fetched.structured_content["status"] == "OPEN"


def test_audit_command_context(mcp_manager: DatabaseSessionManager, mcp_client: ClientHarness) -> None:
    created = mcp_client.call("trace_case_create", {"title": "Context", "lead_examiner": "Analyst"})
    assert created.is_error is False
    events = mcp_client.call("trace_audit_list", {"detail": "full", "limit": 5})
    payload = events.structured_content["items"][0]["payload_json"]
    assert "mcp trace_case_create" in json.dumps(payload)


def test_archive_restore_through_mcp(mcp_client: ClientHarness) -> None:
    created = mcp_client.call("trace_case_create", {"title": "Archive", "lead_examiner": "Analyst"})
    number = created.structured_content["number"]
    archived = mcp_client.call("trace_case_archive", {"identifier": number, "confirm": number})
    assert archived.is_error is False
    restored = mcp_client.call("trace_case_restore", {"identifier": number, "confirm": number})
    assert restored.is_error is False
    assert restored.structured_content["is_deleted"] is False


def test_device_link_unlink(mcp_client: ClientHarness) -> None:
    created = mcp_client.call("trace_case_create", {"title": "Links", "lead_examiner": "Analyst"})
    number = created.structured_content["number"]
    linked = mcp_client.call("trace_device_link", {"node": "/dev/synthetic0", "case_number": number, "confirm": number})
    assert linked.is_error is False
    links = mcp_client.call("trace_device_links", {"case_number": number})
    assert len(links.structured_content["items"]) == 1
    unlinked = mcp_client.call(
        "trace_device_unlink", {"node": "/dev/synthetic0", "case_number": number, "confirm": number}
    )
    assert unlinked.is_error is False
    assert mcp_client.call("trace_device_links", {"case_number": number}).structured_content == {"items": []}


def test_manual_number_requires_confirmation(mcp_client: ClientHarness) -> None:
    response = mcp_client.call(
        "trace_case_create", {"title": "Manual", "lead_examiner": "Analyst", "number": "2026-CR-9999"}
    )
    assert response.is_error is True
    assert "VALIDATION" in response.content[0].text

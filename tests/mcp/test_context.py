import asyncio
import json
import re

from mcp import Client
from mcp.shared.exceptions import MCPError

from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.mcp.server import build_server


def _text(content: object) -> str:
    text = getattr(content, "text", None)
    assert isinstance(text, str)
    return text


def test_resources_and_prompts_are_registered(mcp_manager: DatabaseSessionManager) -> None:
    async def run() -> tuple[list[str], list[str], list[str], str]:
        async with Client(build_server(mcp_manager)) as client:
            resources = [str(r.uri) for r in (await client.list_resources()).resources]
            templates = [t.uri_template for t in (await client.list_resource_templates()).resource_templates]
            prompts = [p.name for p in (await client.list_prompts()).prompts]
            status = _text((await client.read_resource("trace://system/status")).contents[0])
            return resources, templates, prompts, status

    resources, templates, prompts, status = asyncio.run(run())
    assert "trace://system/status" in resources
    assert "trace://cases/{number}" in templates
    assert "trace://audit/{seq}" in templates
    assert "trace://devices/{serial}/history" in templates
    assert set(prompts) == {"case_triage", "audit_integrity_report", "device_intake_checklist"}
    assert json.loads(status)["transport"] == "stdio"


def test_case_and_audit_resources(mcp_manager: DatabaseSessionManager) -> None:
    created = CaseService(mcp_manager).create_case(CaseCreateDto(title="Resource case", lead_examiner="Analyst"))

    async def run() -> tuple[str, str, str]:
        async with Client(build_server(mcp_manager)) as client:
            case = _text((await client.read_resource(f"trace://cases/{created.number}")).contents[0])
            audit = _text((await client.read_resource(f"trace://cases/{created.number}/audit")).contents[0])
            prompt = _text(
                (await client.get_prompt("case_triage", {"case_number": created.number})).messages[0].content
            )
            return case, audit, prompt

    case, audit, prompt = asyncio.run(run())
    assert json.loads(case)["number"] == created.number
    assert json.loads(audit)["items"]
    assert created.number in prompt


def test_audit_and_device_resources(mcp_manager: DatabaseSessionManager) -> None:
    CaseService(mcp_manager).create_case(CaseCreateDto(title="Audit resource case", lead_examiner="Analyst"))

    async def run() -> tuple[str, str]:
        async with Client(build_server(mcp_manager)) as client:
            audit = _text((await client.read_resource("trace://audit/1")).contents[0])
            history = _text((await client.read_resource("trace://devices/SERIAL-X/history")).contents[0])
            return audit, history

    audit, history = asyncio.run(run())
    assert json.loads(audit)["seq"] == 1
    assert json.loads(history) == {"items": []}


def test_missing_case_resource_reports_mapped_code(mcp_manager: DatabaseSessionManager) -> None:
    async def run() -> str:
        async with Client(build_server(mcp_manager)) as client:
            try:
                await client.read_resource("trace://cases/2026-CR-9999")
            except MCPError as exc:
                return str(exc)
        raise AssertionError("resource read should have failed")

    message = asyncio.run(run())
    assert "NOT_FOUND" in message
    assert re.search(r"[0-9a-f]{32}", message) is not None


def test_audit_verify_progress_reports_failure(mcp_manager: DatabaseSessionManager, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from trace_core.core.errors import AuditTamperError
    from trace_core.mcp.tools import audit as audit_tools

    def fail(ctx, on_progress=None):  # type: ignore[no-untyped-def]
        raise AuditTamperError("chain broken")

    monkeypatch.setattr(audit_tools, "_verify", fail)
    seen: list[str | None] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        seen.append(message)

    async def run():
        async with Client(build_server(mcp_manager)) as client:
            return await client.call_tool("trace_audit_verify", {}, progress_callback=on_progress)

    result = asyncio.run(run())
    assert result.is_error is True
    assert seen == ["Scanning ledger", "Verification failed"]


def test_resource_reads_do_not_write_ledger(mcp_manager: DatabaseSessionManager) -> None:
    created = CaseService(mcp_manager).create_case(CaseCreateDto(title="Read-only case", lead_examiner="Analyst"))

    async def run() -> tuple[object, object]:
        async with Client(build_server(mcp_manager)) as client:
            before = (await client.call_tool("trace_audit_list", {})).structured_content
            await client.read_resource("trace://system/status")
            await client.read_resource(f"trace://cases/{created.number}")
            await client.read_resource(f"trace://cases/{created.number}/audit")
            after = (await client.call_tool("trace_audit_list", {})).structured_content
            return before, after

    before, after = asyncio.run(run())
    assert before == after


def test_audit_verify_reports_progress(mcp_manager: DatabaseSessionManager) -> None:
    CaseService(mcp_manager).create_case(CaseCreateDto(title="Progress case", lead_examiner="Analyst"))
    seen: list[float] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        seen.append(progress)

    async def run() -> None:
        async with Client(build_server(mcp_manager)) as client:
            await client.call_tool("trace_audit_verify", {}, progress_callback=on_progress)

    asyncio.run(run())
    assert seen == [0.0, 1.0]

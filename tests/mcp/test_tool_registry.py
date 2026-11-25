from conftest import ClientHarness  # type: ignore[import-not-found]

from trace_core.mcp.constants import ALL_TOOLS, READ_TOOLS, TOOL_AUDIT_KEYS_LIST, TOOL_AUDIT_VERIFY
from trace_core.mcp.tools import DESTRUCTIVE, OPEN_WORLD_READ, READ_ONLY, WRITE


def test_progress_context_is_not_in_tool_schema(mcp_client: ClientHarness) -> None:
    tools = {tool.name: tool for tool in mcp_client.list_tools()}
    properties = tools[TOOL_AUDIT_VERIFY].input_schema.get("properties", {})
    assert "mcp_ctx" not in properties


def test_all_registered_tools_have_strict_schemas(mcp_client: ClientHarness) -> None:
    tools = mcp_client.list_tools()
    assert {tool.name for tool in tools} == ALL_TOOLS
    for tool in tools:
        assert tool.input_schema.get("additionalProperties") is False


def test_keys_list_is_a_read_tool(mcp_client: ClientHarness) -> None:
    assert TOOL_AUDIT_KEYS_LIST in READ_TOOLS
    tools = {tool.name: tool for tool in mcp_client.list_tools()}
    assert tools[TOOL_AUDIT_KEYS_LIST].annotations.read_only_hint is READ_ONLY.read_only_hint


def test_read_tool_annotations(mcp_client: ClientHarness) -> None:
    tools = {tool.name: tool for tool in mcp_client.list_tools()}
    for name in ("trace_status", "trace_case_get", "trace_case_list", "trace_audit_verify"):
        assert tools[name].annotations.read_only_hint is READ_ONLY.read_only_hint
    assert tools["trace_device_list"].annotations.open_world_hint is OPEN_WORLD_READ.open_world_hint


def test_write_annotations(mcp_client: ClientHarness) -> None:
    tools = {tool.name: tool for tool in mcp_client.list_tools()}
    assert tools["trace_case_create"].annotations.read_only_hint is WRITE.read_only_hint
    assert tools["trace_case_close"].annotations.destructive_hint is DESTRUCTIVE.destructive_hint

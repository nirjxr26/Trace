from trace_core.mcp.commands import format_host_result


def test_format_host_result_configured() -> None:
    text = format_host_result(["codex:ok", "claude-code:ok", "zed:failed"], "Trace MCP configured:")
    lines = text.splitlines()
    assert lines[0] == "Trace MCP configured:"
    assert lines[1] == ""
    assert lines[2] == f"    {'Codex':<28} OK"
    assert lines[3] == f"    {'Claude Code':<28} OK"
    assert lines[4] == f"    {'Zed':<28} FAILED"


def test_format_host_result_removed() -> None:
    text = format_host_result(["codex:removed", "claude-code:removed", "opencode:removed"], "Trace MCP removed:")
    lines = text.splitlines()
    assert lines[0] == "Trace MCP removed:"
    assert lines[1] == ""
    assert lines[2] == f"    {'Codex':<28} REMOVED"
    assert lines[3] == f"    {'Claude Code':<28} REMOVED"
    assert lines[4] == f"    {'OpenCode':<28} REMOVED"


def test_format_host_result_colors_only_ok_and_removed() -> None:
    text = format_host_result(["codex:ok", "claude-code:removed", "zed:failed"], "Heading", color=True)
    assert "\033[32mOK\033[0m" in text
    assert "\033[31mREMOVED\033[0m" in text
    assert "FAILED" in text
    assert "\033[31mFAILED" not in text

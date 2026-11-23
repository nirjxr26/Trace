from trace_core.mcp import autoconfig


def test_json_entry_add_and_remove(tmp_path) -> None:
    path = tmp_path / "mcp.json"
    autoconfig._write_json(path, {"other": True})
    entry = {"command": "trace", "args": ["mcp", "serve"]}
    autoconfig._add_json_entry(path, "mcpServers", "trace", entry)
    assert autoconfig._read_json(path)["mcpServers"]["trace"] == entry
    autoconfig._remove_json_entry(path, "mcpServers", "trace")
    assert "trace" not in autoconfig._read_json(path)["mcpServers"]


def test_setup_disabled(monkeypatch) -> None:
    monkeypatch.setenv("TRACE_MCP_DISABLED", "1")
    assert autoconfig.setup() == ["disabled"]


def test_trace_exe_resolves() -> None:
    assert autoconfig.trace_exe()


def test_run_missing_executable_returns_nonzero() -> None:
    result = autoconfig._run(["definitely-not-a-real-trace-cli-executable-xyz"])
    assert result.returncode != 0

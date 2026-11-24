import os
import subprocess

import pytest

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
    executable = autoconfig.trace_exe()
    assert executable
    if os.name == "nt":
        assert executable.lower().endswith(".exe")


def test_run_missing_executable_returns_nonzero() -> None:
    result = autoconfig._run(["definitely-not-a-real-trace-cli-executable-xyz"])
    assert result.returncode != 0


def test_mcp_version_ok() -> None:
    assert autoconfig._mcp_version_ok("2.3.0") is True
    assert autoconfig._mcp_version_ok("2.4.1") is True
    assert autoconfig._mcp_version_ok("1.23.3") is False
    assert autoconfig._mcp_version_ok("not-a-version") is False


def test_ensure_mcp_runtime_skips_when_ready(monkeypatch) -> None:
    monkeypatch.setattr(autoconfig, "_mcp_ready", lambda: True)
    monkeypatch.setattr(autoconfig, "_run", lambda args: pytest.fail("pip must not run"))
    autoconfig.ensure_mcp_runtime()


def test_ensure_mcp_runtime_installs_when_missing(monkeypatch) -> None:
    ready = iter([False, True])
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(autoconfig, "_mcp_ready", lambda: next(ready))
    monkeypatch.setattr(autoconfig, "_run", fake_run)
    autoconfig.ensure_mcp_runtime()
    assert len(calls) == 1
    assert calls[0][1:4] == ["-m", "pip", "install"]
    assert "mcp>=2.3.0,<3" in calls[0]


def test_ensure_mcp_runtime_reports_failure(monkeypatch) -> None:
    monkeypatch.setattr(autoconfig, "_mcp_ready", lambda: False)
    monkeypatch.setattr(
        autoconfig,
        "_run",
        lambda args: subprocess.CompletedProcess(args, 1, "", "boom"),
    )
    with pytest.raises(RuntimeError, match="mcp>=2.3.0,<3"):
        autoconfig.ensure_mcp_runtime()


def test_set_opencode_trace_writes_protocol(tmp_path, monkeypatch) -> None:
    path = tmp_path / "opencode.json"
    monkeypatch.setattr(autoconfig, "_opencode_config_path", lambda: path)
    monkeypatch.setattr(autoconfig, "trace_exe", lambda: "trace")
    autoconfig._set_opencode_trace()
    entry = autoconfig._read_json(path)["mcp"]["servers"]["trace"]
    assert entry["protocol"] == "2026-07-28"
    assert entry["command"] == ["trace", "mcp", "serve"]
    assert "args" not in entry


def test_setup_opencode_falls_back_when_json_write_fails(monkeypatch) -> None:
    monkeypatch.setattr(autoconfig, "_mcp_ready", lambda: True)
    monkeypatch.setattr(autoconfig, "_which", lambda name: name == "opencode")
    calls: list[list[str]] = []

    def fail_write() -> None:
        raise OSError("read-only config")

    def fake_run(args: list[str]):  # type: ignore[no-untyped-def]
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(autoconfig, "_set_desktop", lambda name, disabled: None)
    monkeypatch.setattr(autoconfig, "_json_targets", lambda: [])
    monkeypatch.setattr(autoconfig, "_set_opencode_trace", fail_write)
    monkeypatch.setattr(autoconfig, "_run", fake_run)

    result = autoconfig.setup()
    assert "opencode:ok" in result
    assert calls == [["opencode", "mcp", "add", "--global", "trace", "--", autoconfig.trace_exe(), "mcp", "serve"]]


def test_remove_opencode_trace(tmp_path, monkeypatch) -> None:
    path = tmp_path / "opencode.json"
    autoconfig._write_json(
        path,
        {
            "mcp": {
                "trace": {"type": "local"},
                "servers": {"trace": {"type": "local"}, "other": {"type": "local"}},
            }
        },
    )
    monkeypatch.setattr(autoconfig, "_opencode_config_path", lambda: path)
    autoconfig._remove_opencode_trace()
    data = autoconfig._read_json(path)
    assert "trace" not in data["mcp"]
    assert "trace" not in data["mcp"]["servers"]
    assert "other" in data["mcp"]["servers"]

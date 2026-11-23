import asyncio
import os
import shutil
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).parents[2]


def _trace_exe() -> Path:
    direct = Path(sys.executable).parent / ("trace.exe" if os.name == "nt" else "trace")
    if direct.exists():
        return direct
    scripts = Path(sys.executable).parent / "Scripts" / "trace.exe"
    if scripts.exists():
        return scripts
    found = shutil.which("trace")
    return Path(found) if found else direct


TRACE_EXE = _trace_exe()


def test_trace_exe_uses_scripts_directory(monkeypatch, tmp_path: Path) -> None:
    python_dir = tmp_path / "Python312"
    scripts = python_dir / "Scripts"
    scripts.mkdir(parents=True)
    expected = scripts / "trace.exe"
    expected.touch()
    monkeypatch.setattr(sys, "executable", str(python_dir / "python.exe"))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert _trace_exe() == expected


def test_cli_registers_mcp_help() -> None:
    import subprocess

    result = subprocess.run(
        [str(TRACE_EXE), "mcp", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0
    assert "serve" in result.stdout


def test_stdio_subprocess_serves_tools(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=str(TRACE_EXE),
        args=["mcp", "serve"],
        env={
            **os.environ,
            "TRACE_DATABASE_URL": f"sqlite:///{tmp_path / 'serve.db'}",
            "TRACE_STORAGE_ROOT": str(tmp_path / "storage"),
            "TRACE_SECRET_KEY": "trace-test-key-not-a-real-secret-0123456789abcdef",
        },
        cwd=str(ROOT),
    )

    async def run() -> tuple[list[str], object]:
        async with Client(params) as client:
            tools = [tool.name for tool in (await client.list_tools()).tools]
            status = await client.call_tool("trace_status", {})
        return tools, status

    tools, status = asyncio.run(run())
    assert "trace_status" in tools
    assert status.is_error is False  # type: ignore[attr-defined]

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from trace_core.core.fs import atomic_write_lines


def _disabled() -> bool:
    return os.environ.get("TRACE_MCP_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def trace_exe() -> str:
    exe = shutil.which("trace")
    if exe:
        return exe
    return str(Path(sys.executable).parent / ("trace.exe" if os.name == "nt" else "trace"))


def server_args() -> list[str]:
    return ["mcp", "serve"]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    exe = shutil.which(args[0]) or args[0]
    try:
        return subprocess.run(
            [exe, *args[1:]], capture_output=True, text=True, check=False, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        return subprocess.CompletedProcess(args, 127, "", f"not found: {exc}")


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _desktop_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", "")) / "Claude"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Claude"
    else:
        base = Path.home() / ".config" / "Claude"
    return base / "claude_desktop_config.json"


def _has_trace(cli: str) -> bool:
    result = _run([cli, "mcp", "list"])
    return "trace" in result.stdout


def _set_desktop(name: str, disabled: bool) -> None:
    path = _desktop_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    if disabled:
        servers.pop(name, None)
    else:
        servers[name] = {"command": trace_exe(), "args": server_args()}
    if not servers:
        data.pop("mcpServers", None)
    atomic_write_lines(path, [json.dumps(data, indent=2, ensure_ascii=False) + "\n"])


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_lines(path, [json.dumps(data, indent=2, ensure_ascii=False) + "\n"])


def _add_json_entry(path: Path, key: str, name: str, entry: dict) -> None:
    data = _read_json(path)
    servers = data.setdefault(key, {})
    if not isinstance(servers, dict):
        servers = {}
        data[key] = servers
    servers[name] = entry
    _write_json(path, data)


def _remove_json_entry(path: Path, key: str, name: str) -> None:
    data = _read_json(path)
    servers = data.get(key)
    if isinstance(servers, dict):
        servers.pop(name, None)
        _write_json(path, data)


def _json_targets() -> list[tuple[str, Path, str, bool]]:
    base = Path.home()
    return [
        ("cursor", base / ".cursor" / "mcp.json", "mcpServers", False),
        ("vscode-copilot", base / ".copilot" / "mcp-config.json", "mcpServers", True),
        ("windsurf", base / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers", False),
        ("zed", base / ".config" / "zed" / "mcp.json", "mcpServers", False),
        ("zed-settings", base / ".config" / "zed" / "settings.json", "context_servers", True),
    ]


def setup() -> list[str]:
    if _disabled():
        return ["disabled"]
    done: list[str] = []
    if _which("codex"):
        result = _run(["codex", "mcp", "add", "trace", "--", trace_exe(), *server_args()])
        ok = result.returncode == 0 or _has_trace("codex")
        done.append(f"codex:{'ok' if ok else 'failed'}")
    if _which("claude"):
        result = _run(["claude", "mcp", "add", "trace", "--", trace_exe(), *server_args()])
        ok = result.returncode == 0 or _has_trace("claude")
        done.append(f"claude-code:{'ok' if ok else 'failed'}")
    if _which("opencode"):
        result = _run(["opencode", "mcp", "add", "--global", "trace", "--", trace_exe(), *server_args()])
        ok = result.returncode == 0 or _has_trace("opencode")
        done.append(f"opencode:{'ok' if ok else 'failed'}")
    _set_desktop("trace", disabled=False)
    done.append("claude-desktop:ok")
    for name, path, key, _zed_style in _json_targets():
        _add_json_entry(path, key, "trace", {"command": trace_exe(), "args": server_args()})
        done.append(f"{name}:ok")
    return done


def disable() -> list[str]:
    done: list[str] = []
    for name, cli in (("codex", "codex"), ("claude-code", "claude"), ("opencode", "opencode")):
        if _which(cli):
            _run([cli, "mcp", "remove", "trace"])
            done.append(f"{name}:removed")
    _set_desktop("trace", disabled=True)
    done.append("claude-desktop:removed")
    for name, path, key, _zed_style in _json_targets():
        _remove_json_entry(path, key, "trace")
        done.append(f"{name}:removed")
    return done

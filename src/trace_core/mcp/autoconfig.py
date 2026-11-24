import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from packaging.version import InvalidVersion, Version

from trace_core.core.fs import atomic_write_lines
from trace_core.mcp import MCP_PROTOCOL_VERSION

_CONFIG_DIR = ".config"
_MCP_MIN_VERSION = "2.3.0"
_MCP_REQUIREMENT = "mcp>=2.3.0,<3"


def _disabled() -> bool:
    return os.environ.get("TRACE_MCP_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _mcp_version_ok(version: str) -> bool:
    try:
        return Version(version) >= Version(_MCP_MIN_VERSION)
    except InvalidVersion:
        return False


def _mcp_ready() -> bool:
    if importlib.util.find_spec("mcp") is None:
        return False
    try:
        installed = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return False
    return _mcp_version_ok(installed)


def ensure_mcp_runtime() -> None:
    if _mcp_ready():
        return
    args = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--disable-pip-version-check",
        "--no-input",
        _MCP_REQUIREMENT,
    ]
    result = _run(args)
    if result.returncode != 0:
        _run([sys.executable, "-m", "ensurepip", "--upgrade"])
        result = _run(args)
    if result.returncode != 0 or not _mcp_ready():
        raise RuntimeError(
            f"Could not install MCP support (mcp>={_MCP_MIN_VERSION}) automatically. "
            f'Check network access, then run: python -m pip install "{_MCP_REQUIREMENT}"'
        )


def trace_exe() -> str:
    direct = Path(sys.executable).parent / ("trace.exe" if os.name == "nt" else "trace")
    if direct.exists():
        return str(direct)
    exe = shutil.which("trace")
    if exe:
        return exe
    return str(direct)


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
        base = Path.home() / _CONFIG_DIR / "Claude"
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


def _opencode_config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / _CONFIG_DIR)))
    return base / "opencode" / "opencode.json"


def _remove_opencode_trace() -> None:
    path = _opencode_config_path()
    data = _read_json(path)
    mcp = data.get("mcp")
    if not isinstance(mcp, dict):
        return
    changed = False
    if "trace" in mcp:
        mcp.pop("trace")
        changed = True
    servers = mcp.get("servers")
    if isinstance(servers, dict) and "trace" in servers:
        servers.pop("trace")
        changed = True
    if changed:
        _write_json(path, data)


def _set_opencode_trace() -> None:
    path = _opencode_config_path()
    data = _read_json(path)
    mcp = data.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        mcp = {}
        data["mcp"] = mcp
    servers = mcp.setdefault("servers", {})
    if not isinstance(servers, dict):
        servers = {}
        mcp["servers"] = servers
    servers["trace"] = {
        "type": "local",
        "command": [trace_exe(), *server_args()],
        "protocol": MCP_PROTOCOL_VERSION,
    }
    _write_json(path, data)


def _json_targets() -> list[tuple[str, Path, str, bool]]:
    base = Path.home()
    return [
        ("cursor", base / ".cursor" / "mcp.json", "mcpServers", False),
        ("vscode-copilot", base / ".copilot" / "mcp-config.json", "mcpServers", True),
        ("windsurf", base / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers", False),
        ("zed", base / _CONFIG_DIR / "zed" / "mcp.json", "mcpServers", False),
        ("zed-settings", base / _CONFIG_DIR / "zed" / "settings.json", "context_servers", True),
    ]


def _register_cli_host(name: str, cli: str, done: list[str]) -> None:
    if not _which(cli):
        return
    result = _run([cli, "mcp", "add", "trace", "--", trace_exe(), *server_args()])
    ok = result.returncode == 0 or _has_trace(cli)
    done.append(f"{name}:{'ok' if ok else 'failed'}")


def _register_opencode(done: list[str]) -> None:
    if not _which("opencode"):
        return
    try:
        _set_opencode_trace()
        done.append("opencode:ok")
        return
    except OSError:
        pass
    result = _run(["opencode", "mcp", "add", "--global", "trace", "--", trace_exe(), *server_args()])
    ok = result.returncode == 0 or _has_trace("opencode")
    if ok:
        try:
            _set_opencode_trace()
        except OSError:
            pass
    done.append(f"opencode:{'ok' if ok else 'failed'}")


def _register_json_hosts(done: list[str]) -> None:
    _set_desktop("trace", disabled=False)
    done.append("claude-desktop:ok")
    for name, path, key, _zed_style in _json_targets():
        _add_json_entry(path, key, "trace", {"command": trace_exe(), "args": server_args()})
        done.append(f"{name}:ok")


def setup(on_progress: Callable[[str], None] | None = None) -> list[str]:
    if _disabled():
        return ["disabled"]
    if on_progress:
        on_progress("Checking MCP support. This may take a moment...")
    ensure_mcp_runtime()
    if on_progress:
        on_progress("Registering hosts. This may take a few seconds...")
    done: list[str] = []
    _register_cli_host("codex", "codex", done)
    _register_cli_host("claude-code", "claude", done)
    _register_opencode(done)
    _register_json_hosts(done)
    return done


def disable(on_progress: Callable[[str], None] | None = None) -> list[str]:
    if on_progress:
        on_progress("Removing host configuration. This may take a few seconds...")
    done: list[str] = []
    for name, cli in (("codex", "codex"), ("claude-code", "claude")):
        if _which(cli):
            _run([cli, "mcp", "remove", "trace"])
            done.append(f"{name}:removed")
    _remove_opencode_trace()
    done.append("opencode:removed")
    _set_desktop("trace", disabled=True)
    done.append("claude-desktop:removed")
    for name, path, key, _zed_style in _json_targets():
        _remove_json_entry(path, key, "trace")
        done.append(f"{name}:removed")
    return done

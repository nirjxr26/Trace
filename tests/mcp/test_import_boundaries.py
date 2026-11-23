import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
MCP_PACKAGE = ROOT / "src" / "trace_core" / "mcp"
FORBIDDEN_MODULES = {
    "trace_core.cases.repository",
    "trace_core.cases.models",
    "trace_core.devices.repository",
    "trace_core.devices.models",
    "trace_core.audit.repository",
    "trace_core.audit.models",
    "trace_core.imaging.repository",
    "trace_core.imaging.models",
    "sqlalchemy",
}


def test_mcp_package_never_imports_repositories_or_orm() -> None:
    for path in MCP_PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in FORBIDDEN_MODULES, f"{path}: {alias.name}"
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in FORBIDDEN_MODULES, f"{path}: {node.module}"
                assert node.module == "sqlalchemy.exc" or not node.module.startswith("sqlalchemy"), (
                    f"{path}: {node.module}"
                )


def test_mcp_package_never_calls_session_add() -> None:
    for path in MCP_PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "add", f"{path}: session.add-style call"

import asyncio
from pathlib import Path
from typing import Any

import pytest

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.operators import bootstrap_current_operator
from trace_core.mcp.server import build_server


class ClientHarness:
    def __init__(self, server: Any) -> None:
        self.server = server

    def list_tools(self) -> list[Any]:
        async def run() -> list[Any]:
            from mcp import Client

            async with Client(self.server) as client:
                return list((await client.list_tools()).tools)

        return asyncio.run(run())

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        async def run() -> Any:
            from mcp import Client

            async with Client(self.server) as client:
                return await client.call_tool(name, arguments or {})

        return asyncio.run(run())


@pytest.fixture
def mcp_manager(tmp_path: Path) -> DatabaseSessionManager:
    manager = DatabaseSessionManager(f"sqlite:///{tmp_path / 'trace-mcp.db'}")
    manager.init_schema()
    bootstrap_current_operator(manager)
    return manager


@pytest.fixture
def mcp_client(mcp_manager: DatabaseSessionManager) -> ClientHarness:
    return ClientHarness(build_server(mcp_manager))

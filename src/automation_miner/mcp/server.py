"""Stdio MCP server (``automation-miner-mcp``).

Uses the optional ``mcp`` package. Tool logic lives in ``tools.py`` so it can
be tested without the mcp dependency or a stdio transport.
"""

from __future__ import annotations

import json
from typing import Any

from automation_miner import __version__
from automation_miner.artifacts.workspace import default_workspace
from automation_miner.mcp.tools import TOOL_DESCRIPTIONS, TOOL_SCHEMAS, dispatch


def main() -> None:
    """Run the stdio MCP server. Requires the ``mcp`` extra."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError as exc:
        raise SystemExit(
            "The 'mcp' package is required: pip install 'automation-miner[mcp]'"
        ) from exc

    workspace = default_workspace()
    server: Any = Server(f"automation-miner-mcp@{__version__}")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=TOOL_DESCRIPTIONS[name],
                inputSchema=TOOL_SCHEMAS[name],
            )
            for name in sorted(TOOL_SCHEMAS)
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        response = await asyncio.to_thread(dispatch, name, dict(arguments or {}), workspace)
        return [TextContent(type="text", text=json.dumps(response.to_dict(), default=str))]

    import asyncio

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()

"""MCP interface: tool handlers (mcp-free) plus the optional stdio server."""

from automation_miner.mcp.errors import MCPError, MCPErrorCode, MCPResponse
from automation_miner.mcp.tools import HANDLERS, TOOL_SCHEMAS, dispatch

__all__ = ["HANDLERS", "MCPError", "MCPErrorCode", "MCPResponse", "TOOL_SCHEMAS", "dispatch"]

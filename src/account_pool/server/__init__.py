"""The agent-facing MCP server (FastMCP) — tools (mutations) and resources (read-first reflection)."""

from .mcp_server import build_mcp, main

__all__ = ["build_mcp", "main"]

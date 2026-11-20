"""MCP adapter tests. Skipped (not failed) if no compatible MCP SDK is installed."""
import asyncio
import sys
from pathlib import Path

import pytest

from fakes import FakeSearch

try:
    from agent.mcp.server import build_mcp_server, MCPUnavailable, _server_class
    _server_class()
    HAVE_MCP = True
except Exception:
    HAVE_MCP = False

pytestmark = pytest.mark.skipif(not HAVE_MCP, reason="No compatible MCP SDK installed")


def test_mcp_exposes_only_read_only_tools(store):
    from agent.tools.builtin import build_tool_registry
    server = build_mcp_server(build_tool_registry(store, search_fn=FakeSearch()))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"web_search", "web_page_reader", "provider_search", "find_slots"}
    assert "request_appointment" not in names


def test_mcp_tool_call_returns_real_tool_result(store):
    from agent.tools.builtin import build_tool_registry
    server = build_mcp_server(build_tool_registry(store, search_fn=FakeSearch()))
    result = asyncio.run(server.call_tool("web_search", {"query": "respite care"}))
    assert "mayoclinic.org" in str(result)


def test_mcp_stdio_roundtrip(tmp_path):
    """Start the real server over stdio and call list_tools from an MCP client."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        pytest.skip("MCP client API not available")
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(command=sys.executable, args=["-m", "agent.mcp.server"],
                                   cwd=str(root),
                                   env={"PYTHONPATH": str(root),
                                        "NEUROBRIDGE_BOOKING_DB": str(tmp_path / "b.sqlite3")})

    async def go():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return {t.name for t in tools.tools}

    names = asyncio.run(asyncio.wait_for(go(), timeout=30))
    assert "web_search" in names

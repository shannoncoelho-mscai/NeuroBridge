"""NeuroBridge MCP server (optional, isolated component).

Exposes NeuroBridge's READ-ONLY tools over the Model Context Protocol:
  web_search, web_page_reader, provider_search, find_slots
Consequential tools (request/cancel appointment) are NOT exposed: MCP clients have no
NeuroBridge approval channel, and booking must stay caregiver-approved via the API/UI.

Version tolerance: works with mcp 2.x (mcp.server.mcpserver.MCPServer) and mcp 1.x
(mcp.server.fastmcp.FastMCP). It never installs or changes packages. If neither import
works, build_mcp_server() raises MCPUnavailable and nothing else in NeuroBridge is affected.

Run (stdio):  python -m agent.mcp.server
"""
from typing import List, Optional


class MCPUnavailable(RuntimeError):
    pass


def _server_class():
    try:
        from mcp.server.mcpserver import MCPServer  # mcp >= 2
        return MCPServer, "mcp2"
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP  # mcp 1.x
        return FastMCP, "mcp1"
    except ImportError as exc:
        raise MCPUnavailable(f"No compatible MCP SDK found: {exc}")


READ_ONLY_TOOLS = ("web_search", "web_page_reader", "provider_search", "find_slots")


def build_mcp_server(tool_registry=None, booking_store=None):
    cls, flavour = _server_class()
    if tool_registry is None:
        from agent.tools.booking_db import BookingStore
        from agent.tools.builtin import build_tool_registry
        tool_registry = build_tool_registry(booking_store=booking_store or BookingStore())

    server = cls(name="neurobridge",
                 instructions=("NeuroBridge caregiver-support research tools. Read-only. "
                               "Results come from live tools; nothing is invented."))
    available = {t["name"] for t in tool_registry.list_tools()}

    def _run(name, **kwargs):
        args = {k: v for k, v in kwargs.items() if v is not None}
        result = tool_registry.execute(name=name, arguments=args)
        return {"status": result["status"], "result": result["result"], "error": result["error"]}

    if "web_search" in available:
        def web_search(query: str, max_results: int = 5) -> dict:
            """Search the web. Returns titles, URLs and snippets."""
            return _run("web_search", query=query, max_results=max_results)
        server.add_tool(web_search, name="web_search")

    if "web_page_reader" in available:
        def web_page_reader(urls: List[str]) -> dict:
            """Extract text from up to 3 public web pages."""
            return _run("web_page_reader", urls=urls)
        server.add_tool(web_page_reader, name="web_page_reader")

    if "provider_search" in available:
        def provider_search(profession: Optional[str] = None, specialty: Optional[str] = None,
                            language: Optional[str] = None, location: Optional[str] = None,
                            child_age: Optional[int] = None) -> dict:
            """Search VERIFIED providers in the NeuroBridge registry."""
            return _run("provider_search", profession=profession, specialty=specialty,
                        language=language, location=location, child_age=child_age)
        server.add_tool(provider_search, name="provider_search")

    if "find_slots" in available:
        def find_slots(provider_id: Optional[int] = None, location: Optional[str] = None,
                       specialty: Optional[str] = None, child_age: Optional[int] = None) -> dict:
            """List available slots of verified providers (read-only; booking needs the app)."""
            return _run("find_slots", provider_id=provider_id, location=location,
                        specialty=specialty, child_age=child_age)
        server.add_tool(find_slots, name="find_slots")

    server.neurobridge_flavour = flavour
    return server


if __name__ == "__main__":
    build_mcp_server().run("stdio")

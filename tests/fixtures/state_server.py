from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("irigate-test-state")
state: str | None = None


@server.tool(name="set_state")
def set_state(value: str) -> dict[str, str]:
    global state
    state = value
    return {"value": value}


@server.tool(name="get_state")
def get_state() -> dict[str, str | None]:
    return {"value": state}


if __name__ == "__main__":
    server.run(transport="stdio")

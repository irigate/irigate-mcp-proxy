from __future__ import annotations

import anyio
from mcp.server.fastmcp import FastMCP

server = FastMCP("irigate-spike-echo")


@server.tool(name="repeat")
async def repeat(value: str, delay_seconds: float = 0.0) -> dict[str, str]:
    """Return the supplied value after an optional bounded delay."""
    if delay_seconds:
        await anyio.sleep(delay_seconds)
    return {"value": value}


if __name__ == "__main__":
    server.run(transport="stdio")

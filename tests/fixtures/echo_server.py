from __future__ import annotations

import anyio
from mcp.server.fastmcp import FastMCP

server = FastMCP("irigate-test-echo")


@server.tool(name="repeat")
async def repeat(value: str, delay_seconds: float = 0.0) -> dict[str, str]:
    if delay_seconds:
        await anyio.sleep(delay_seconds)
    return {"value": value}


@server.tool(name="terminate")
def terminate() -> None:
    import os

    os._exit(23)


if __name__ == "__main__":
    server.run(transport="stdio")

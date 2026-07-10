from __future__ import annotations

import os
from mcp.server.fastmcp import FastMCP

server = FastMCP("irigate-spike-crash-fixture")


@server.tool(name="repeat")
def repeat(value: str) -> dict[str, str]:
    return {"value": value}


@server.tool(name="terminate")
def terminate() -> None:
    os._exit(23)


if __name__ == "__main__":
    server.run(transport="stdio")

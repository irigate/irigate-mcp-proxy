from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

server = FastMCP("irigate-test-workspace")
workspace = sys.argv[1]


@server.tool(name="workspace")
def selected_workspace() -> dict[str, str]:
    return {"workspace": workspace}


if __name__ == "__main__":
    server.run(transport="stdio")

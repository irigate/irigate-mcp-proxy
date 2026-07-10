from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("context7-readonly-test")


@server.tool(name="resolve-library-id")
def resolve_library_id(library_name: str = "test") -> dict[str, str]:
    return {"library_id": f"/test/{library_name}"}


@server.tool(name="query-docs")
def query_docs(library_id: str = "/test/library") -> dict[str, str]:
    return {"content": library_id}


@server.tool(name="terminate")
def terminate() -> None:
    import os

    os._exit(23)


if __name__ == "__main__":
    server.run(transport="stdio")

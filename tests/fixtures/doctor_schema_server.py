from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

server = FastMCP("irigate-doctor-schema-fixture")


@server.tool(name="export_html")
def export_html(
    filePath: str, outputPath: str, prompt: str = ""
) -> dict[str, str]:
    return {"filePath": filePath, "outputPath": outputPath, "prompt": prompt}


@server.tool(name="export_nodes")
def export_nodes(filePath: str, outputDir: str) -> dict[str, str]:
    return {"filePath": filePath, "outputDir": outputDir}


@server.tool(name="visit")
def visit(url: str) -> dict[str, str]:
    return {"url": url}


if __name__ == "__main__":
    server.run(transport="stdio")

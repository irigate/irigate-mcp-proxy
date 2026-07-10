from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("SPIKE_PORT", "8765"))
UPSTREAM_TIMEOUT_SECONDS = 0.20


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[dict[str, Any]]:
    params = StdioServerParameters(
        command=os.environ.get("SPIKE_PYTHON", sys.executable),
        args=[str(HERE / "echo_server.py")],
    )
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield {"echo": session}


broker = FastMCP(
    "irigate-transport-spike",
    host=HOST,
    port=PORT,
    streamable_http_path="/mcp",
    json_response=True,
    lifespan=lifespan,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{HOST}:{PORT}", f"localhost:{PORT}"],
        allowed_origins=[f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"],
    ),
)


@broker.tool(name="echo__repeat")
async def echo_repeat(value: str, delay_seconds: float = 0.0, ctx: Context | None = None) -> dict[str, Any]:
    """Forward one namespaced call to the persistent stdio echo upstream."""
    if ctx is None:
        raise RuntimeError("request context is required")
    session = ctx.request_context.lifespan_context["echo"]
    with anyio.fail_after(UPSTREAM_TIMEOUT_SECONDS):
        result = await session.call_tool(
            "repeat",
            {"value": value, "delay_seconds": delay_seconds},
        )
    call_log = os.environ.get("SPIKE_CALL_LOG")
    if call_log:
        with Path(call_log).open("a", encoding="utf-8") as handle:
            handle.write("echo__repeat\n")
    if result.structuredContent is None:
        raise RuntimeError("echo upstream omitted structured content")
    return result.structuredContent


if __name__ == "__main__":
    broker.run(transport="streamable-http")

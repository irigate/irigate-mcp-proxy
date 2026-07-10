from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import StdioServerParameters
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from upstream_worker import UpstreamWorker

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("SPIKE_PORT", "8766"))


def params(command: str, *args: str) -> StdioServerParameters:
    return StdioServerParameters(command=command, args=list(args))


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[dict[str, Any]]:
    workers = {
        "crg": UpstreamWorker(params("uvx", "code-review-graph", "serve")),
        "context7": UpstreamWorker(params("npx", "-y", "@upstash/context7-mcp")),
        "crash": UpstreamWorker(params(sys.executable, str(HERE / "crash_server.py")), timeout_seconds=5.0),
    }
    schemas = {}
    try:
        for key, worker in workers.items():
            schemas[key] = await worker.start()
        yield {"workers": workers, "schemas": schemas}
    finally:
        for worker in workers.values():
            await worker.close()


broker = FastMCP(
    "irigate-sharing-spike",
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


def worker(ctx: Context, key: str) -> UpstreamWorker:
    return ctx.request_context.lifespan_context["workers"][key]


def result_text(result: Any) -> str:
    return "\n".join(getattr(item, "text", "") for item in result.content)


@broker.tool(name="crg__list_graph_stats")
async def crg_list_graph_stats(repo_root: str, ctx: Context) -> str:
    result = await worker(ctx, "crg").call("list_graph_stats_tool", {"repo_root": repo_root})
    if result.isError:
        raise RuntimeError(result_text(result))
    return result_text(result)


@broker.tool(name="context7__resolve_library_id")
async def context7_resolve_library_id(query: str, library_name: str, ctx: Context) -> str:
    result = await worker(ctx, "context7").call(
        "resolve-library-id",
        {"query": query, "libraryName": library_name},
    )
    if result.isError:
        raise RuntimeError(result_text(result))
    return result_text(result)


@broker.tool(name="crash__repeat")
async def crash_repeat(value: str, ctx: Context) -> str:
    result = await worker(ctx, "crash").call("repeat", {"value": value})
    if result.isError:
        raise RuntimeError(result_text(result))
    return result_text(result)


@broker.tool(name="crash__terminate")
async def crash_terminate(ctx: Context) -> str:
    try:
        await worker(ctx, "crash").call("terminate", {})
    except RuntimeError as exc:
        return f"contained: {type(exc).__name__}"
    raise RuntimeError("crash fixture unexpectedly survived")


if __name__ == "__main__":
    broker.run(transport="streamable-http")

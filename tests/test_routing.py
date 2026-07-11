from __future__ import annotations

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.helpers import running_broker, upstream

pytestmark = pytest.mark.asyncio


async def call(url: str, name: str, arguments: dict[str, object]):
    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)


async def test_namespaced_tool_routes_to_exact_upstream() -> None:
    async with running_broker({"echo": upstream()}, selector="upstreams=echo") as url:
        result = await call(url, "echo__repeat", {"value": "routed"})

    assert result.isError is False
    assert result.structuredContent == {"value": "routed"}


async def test_unknown_prefix_fails_without_fallback() -> None:
    async with running_broker({"echo": upstream()}, selector="upstreams=echo") as url:
        result = await call(url, "missing__repeat", {"value": "not-routed"})

    assert result.isError is True
    assert "unknown upstream prefix" in result.content[0].text


async def test_unknown_tool_under_known_prefix_fails() -> None:
    async with running_broker({"echo": upstream()}, selector="upstreams=echo") as url:
        result = await call(url, "echo__missing", {})

    assert result.isError is True
    assert "unknown tool" in result.content[0].text

from __future__ import annotations

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.helpers import running_broker, upstream

pytestmark = pytest.mark.asyncio


async def test_downstream_initialize_and_list_tools() -> None:
    async with running_broker({"echo": upstream()}) as url:
        assert "?" not in url
        assert "@" not in url.removeprefix("http://")
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                result = await session.initialize()
                tools = await session.list_tools()

    assert result.serverInfo.name == "irigate"
    assert [tool.name for tool in tools.tools] == ["echo__repeat", "echo__terminate"]


async def test_origin_policy_rejects_remote_and_malformed_origins() -> None:
    async with running_broker({"echo": upstream()}) as url:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "origin-test", "version": "1"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        async with httpx.AsyncClient() as client:
            remote = await client.post(url, json=payload, headers={**headers, "Origin": "https://remote.example"})
            malformed = await client.post(url, json=payload, headers={**headers, "Origin": "not-an-origin"})
            no_origin = await client.post(url, json=payload, headers=headers)
            loopback = await client.post(url, json=payload, headers={**headers, "Origin": url.removesuffix("/mcp")})

    assert remote.status_code == 403
    assert malformed.status_code == 403
    assert no_origin.status_code == 200
    assert loopback.status_code == 200

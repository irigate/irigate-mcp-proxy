from __future__ import annotations

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.helpers import running_broker, upstream

pytestmark = pytest.mark.asyncio


async def test_downstream_initialize_and_list_tools() -> None:
    async with running_broker({"echo": upstream()}, selector="upstreams=echo") as url:
        assert url.endswith("?upstreams=echo")
        assert "@" not in url.removeprefix("http://")
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                result = await session.initialize()
                tools = await session.list_tools()

    assert result.serverInfo.name == "irigate"
    assert [tool.name for tool in tools.tools] == ["echo__repeat", "echo__terminate"]


async def test_omitted_selector_exposes_all_configured_upstreams() -> None:
    async with running_broker(
        {"echo": upstream(), "other": upstream()}, selector="upstreams=echo"
    ) as selected_url:
        url = selected_url.split("?", maxsplit=1)[0]
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = await session.list_tools()

    assert [tool.name for tool in tools.tools] == [
        "echo__repeat",
        "echo__terminate",
        "other__repeat",
        "other__terminate",
    ]


async def test_origin_policy_rejects_remote_and_malformed_origins() -> None:
    async with running_broker({"echo": upstream()}, selector="upstreams=echo") as url:
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
            loopback = await client.post(
                url,
                json=payload,
                headers={**headers, "Origin": url.split("/mcp", maxsplit=1)[0]},
            )

    assert remote.status_code == 403
    assert malformed.status_code == 403
    assert no_origin.status_code == 200
    assert loopback.status_code == 200


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("tools=echo__repeat&upstreams=echo", "exactly one selector"),
        ("tools=echo__repeat&tools=echo__terminate", "repeated selector"),
        ("upstreams=echo&extra=value", "unsupported query parameter"),
        ("upstreams=missing", "unknown upstream"),
    ],
)
async def test_rejects_invalid_agent_selector(query: str, message: str) -> None:
    async with running_broker({"echo": upstream()}, selector="upstreams=echo") as url:
        endpoint = url.split("?", maxsplit=1)[0]
        if query:
            endpoint = f"{endpoint}?{query}"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "selection-test", "version": "1"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        async with httpx.AsyncClient() as client:
            response = await client.post(endpoint, json=payload, headers=headers)

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert message in body["error"]


async def test_decodes_reverse_selector_from_url() -> None:
    async with running_broker(
        {"echo": upstream(), "other": upstream()}, selector="upstreams=%21other"
    ) as url:
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                result = await session.initialize()

    assert result.serverInfo.name == "irigate"

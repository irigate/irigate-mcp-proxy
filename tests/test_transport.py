from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.helpers import ECHO_SERVER, running_broker, upstream

pytestmark = pytest.mark.asyncio


def filesystem_upstream(root: Path) -> dict[str, object]:
    configured = upstream(args=[str(ECHO_SERVER), "{workspace}"])
    configured["inputs"] = {
        "workspace": {
            "type": "directory",
            "required": True,
            "allowed_roots": [str(root)],
        }
    }
    return configured


def initialize_payload() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "workspace-test", "version": "1"},
        },
    }


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
        ("upstreams=echo&agent=bad%20name", "invalid agent name"),
        ("upstreams=echo&agent=codex&agent=hermes", "repeated agent"),
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


async def test_accepts_explicit_agent_with_selector() -> None:
    async with running_broker(
        {"echo": upstream()}, selector="upstreams=echo&agent=codex"
    ) as url:
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool("echo__repeat", {"value": "tagged"})

    assert result.isError is False


async def test_explicit_workspace_input_exposes_only_filesystem_tools(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    selector = urlencode(
        {
            "upstreams": "filesystem",
            "filesystem.workspace": str(workspace),
        }
    )
    async with running_broker(
        {
            "filesystem": filesystem_upstream(tmp_path),
            "other": upstream(),
        },
        selector=selector,
    ) as url:
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = await session.list_tools()

    assert [tool.name for tool in tools.tools] == [
        "filesystem__repeat",
        "filesystem__terminate",
    ]


async def test_invalid_workspace_returns_json_400(tmp_path: Path) -> None:
    async with running_broker(
        {"filesystem": filesystem_upstream(tmp_path)},
        selector="upstreams=filesystem",
    ) as selected_url:
        endpoint = selected_url.split("?", maxsplit=1)[0]
        endpoint = f"{endpoint}?upstreams=filesystem&filesystem.workspace=relative"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint,
                json=initialize_payload(),
                headers={"Accept": "application/json, text/event-stream"},
            )

    assert response.status_code == 400
    assert response.json() == {"error": "workspace must be an explicit absolute path"}


async def test_rejects_workspace_rebinding_for_existing_session(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    async with running_broker(
        {"filesystem": filesystem_upstream(tmp_path)},
        selector="upstreams=filesystem",
    ) as selected_url:
        endpoint = selected_url.split("?", maxsplit=1)[0]
        first_query = urlencode(
            {"upstreams": "filesystem", "filesystem.workspace": str(first)}
        )
        second_query = urlencode(
            {"upstreams": "filesystem", "filesystem.workspace": str(second)}
        )
        first_url = f"{endpoint}?{first_query}"
        second_url = f"{endpoint}?{second_query}"
        headers = {"Accept": "application/json, text/event-stream"}
        async with httpx.AsyncClient() as client:
            initialized = await client.post(
                first_url,
                json=initialize_payload(),
                headers=headers,
            )
            session_id = initialized.headers["mcp-session-id"]
            rebound = await client.post(
                second_url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={**headers, "mcp-session-id": session_id},
            )

    assert initialized.status_code == 200
    assert rebound.status_code == 400
    assert rebound.json() == {"error": "session inputs cannot be changed"}

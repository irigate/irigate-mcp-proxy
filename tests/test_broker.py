from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from irigate.broker import Broker, BrokerInitializationError
from irigate.models import BrokerConfig
from tests.helpers import config_for, running_broker, upstream

pytestmark = pytest.mark.asyncio


async def test_rejects_duplicate_tool_names_from_one_upstream() -> None:
    broker = Broker(config_for(8765, {"echo": upstream()}))
    duplicates = [
        types.Tool(name="repeat", inputSchema={"type": "object"}),
        types.Tool(name="repeat", inputSchema={"type": "object"}),
    ]

    with pytest.raises(BrokerInitializationError, match="duplicate tool name"):
        broker.namespace_tools("echo", duplicates)


async def test_upstream_initialization_failure_is_safe() -> None:
    config = config_for(
        8765,
        {"broken": upstream(command="irigate-command-that-does-not-exist", args=[])},
    )
    broker = Broker(config)

    with pytest.raises(BrokerInitializationError, match="broken") as exc_info:
        await broker.start()

    assert "irigate-command-that-does-not-exist" not in str(exc_info.value)
    await broker.close()


async def test_call_timeout_returns_error() -> None:
    async with running_broker(
        {"echo": upstream(timeout=0.05)}, selector="upstreams=echo"
    ) as url:
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "echo__repeat", {"value": "slow", "delay_seconds": 0.5}
                )

    assert result.isError is True
    assert "timed out" in result.content[0].text


async def test_upstream_crash_does_not_stop_another_upstream() -> None:
    async with running_broker(
        {"crash": upstream(), "healthy": upstream()},
        selector="upstreams=crash,healthy",
    ) as url:
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                crashed = await session.call_tool("crash__terminate", {})
                healthy = await session.call_tool("healthy__repeat", {"value": "still-running"})

    assert crashed.isError is True
    assert healthy.isError is False
    assert healthy.structuredContent == {"value": "still-running"}


async def test_shareable_worker_reused_and_isolated_worker_scoped_per_session() -> None:
    context7_server = Path(__file__).parent / "fixtures" / "context7_server.py"
    config = BrokerConfig.model_validate(
        {
            "name": "lifecycle-test",
            "host": "127.0.0.1",
            "port": 8765,
            "upstreams": {
                "context7": upstream(
                    args=[str(context7_server)],
                    shareable=True, qualifier="context7-readonly-v3"
                ),
                "isolated": upstream(),
            },
        }
    )
    broker = Broker(config)
    await broker.start()
    try:
        shared_a = await broker.worker_for("context7", "session-a")
        shared_b = await broker.worker_for("context7", "session-b")
        isolated_a = await broker.worker_for("isolated", "session-a")
        isolated_b = await broker.worker_for("isolated", "session-b")

        assert shared_a is shared_b
        assert isolated_a is not isolated_b
    finally:
        await broker.close()

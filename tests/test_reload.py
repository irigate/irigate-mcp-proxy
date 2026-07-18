from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

import pytest
import uvicorn
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from irigate.app import create_app
from irigate.broker import Broker, BrokerInitializationError
from irigate.config import ConfigurationError, load_config
from irigate.selection import parse_selection
from tests.helpers import ECHO_SERVER, config_for, upstream

pytestmark = pytest.mark.asyncio
STATE_SERVER = Path(__file__).parent / "fixtures" / "state_server.py"


def write_profile(path: Path, port: int, server: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "name": "reload-test",
                "host": "127.0.0.1",
                "port": port,
                "upstreams": {
                    "fixture": {
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": [str(server)],
                        "env": {},
                        "shareable": False,
                        "concurrency": "serial",
                        "call_timeout_seconds": 1,
                        "idle_timeout_seconds": 60,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


async def test_background_reload_restarts_changed_upstream_without_disconnect(
    tmp_path: Path,
) -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    profile = tmp_path / "profile.yaml"
    write_profile(profile, port, ECHO_SERVER)
    app = create_app(
        load_config(profile), config_path=profile, reload_interval_seconds=0.02
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("test broker did not start")

        async with streamable_http_client(
            f"http://127.0.0.1:{port}/mcp?upstreams=fixture"
        ) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                before = await session.call_tool("fixture__repeat", {"value": "before"})
                assert before.structuredContent == {"value": "before"}

                write_profile(profile, port, STATE_SERVER)
                for _ in range(200):
                    tools = await session.list_tools()
                    if [tool.name for tool in tools.tools] == [
                        "fixture__set_state",
                        "fixture__get_state",
                    ]:
                        break
                    await asyncio.sleep(0.02)
                else:
                    raise TimeoutError("configuration was not reloaded")

                after = await session.call_tool("fixture__get_state", {})
                assert after.isError is False
                assert after.structuredContent == {"value": None}
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)


async def test_failed_reload_keeps_current_upstream_available() -> None:
    broker = Broker(config_for(8765, {"fixture": upstream()}))
    await broker.start()
    try:
        await broker.call_tool("fixture__repeat", {"value": "active"}, "client")
        broken = config_for(
            8765,
            {
                "fixture": upstream(
                    command="irigate-command-that-does-not-exist", args=[]
                )
            },
        )
        with pytest.raises(BrokerInitializationError, match="fixture"):
            await broker.reload(broken)

        result = await broker.call_tool(
            "fixture__repeat", {"value": "still-running"}, "client"
        )
        assert result.isError is False
        assert result.structuredContent == {"value": "still-running"}
    finally:
        await broker.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "other-profile"),
        ("host", "localhost"),
        ("port", 8766),
        ("runtime_report_path", Path("/tmp/other-report.json")),
        ("runtime_log_path", Path("/tmp/other-logs")),
    ],
)
async def test_reload_rejects_startup_bound_profile_fields(
    field: str, value: object
) -> None:
    config = config_for(8765, {"fixture": upstream()})
    broker = Broker(config)
    await broker.start()
    try:
        replacement = config.model_copy(update={field: value})

        with pytest.raises(ConfigurationError, match=field):
            await broker.reload(replacement)
    finally:
        await broker.close()


async def test_reload_keeps_changed_dormant_upstream_unstarted() -> None:
    broker = Broker(config_for(8765, {"fixture": upstream()}))
    await broker.start()
    try:
        changed = config_for(
            8765,
            {
                "fixture": upstream(
                    command="irigate-command-that-does-not-exist", args=[]
                )
            },
        )
        assert await broker.reload(changed) is True
        assert broker.runtime_snapshot()["upstreams"]["fixture"]["spawns"] == 0

        with pytest.raises(BrokerInitializationError, match="fixture"):
            await broker.call_tool("fixture__repeat", {}, "client")
    finally:
        await broker.close()


async def test_reload_adds_upstream_without_starting_it() -> None:
    broker = Broker(config_for(8765, {"fixture": upstream()}))
    await broker.start()
    try:
        replacement = config_for(
            8765, {"fixture": upstream(), "added": upstream()}
        )
        assert await broker.reload(replacement) is True
        assert broker.runtime_snapshot()["upstreams"]["added"]["spawns"] == 0

        selection = parse_selection((("upstreams", "added"),), replacement.upstreams)
        assert [tool.name for tool in await broker.list_tools(selection)] == [
            "added__repeat",
            "added__terminate",
        ]
        assert broker.runtime_snapshot()["upstreams"]["added"]["spawns"] >= 1
    finally:
        await broker.close()

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn

from irigate.app import create_app
from irigate.models import BrokerConfig

ROOT = Path(__file__).resolve().parents[1]
ECHO_SERVER = ROOT / "tests" / "fixtures" / "echo_server.py"


def upstream(
    *,
    command: str | None = None,
    args: list[str] | None = None,
    shareable: bool = False,
    qualifier: str | None = None,
    timeout: float = 1.0,
) -> dict[str, Any]:
    return {
        "transport": "stdio",
        "command": command or str(Path(__import__("sys").executable)),
        "args": args or [str(ECHO_SERVER)],
        "env": {},
        "shareable": shareable,
        "qualifier": qualifier,
        "concurrency": "serial",
        "call_timeout_seconds": timeout,
    }


def config_for(port: int, upstreams: dict[str, dict[str, Any]]) -> BrokerConfig:
    return BrokerConfig.model_validate(
        {
            "name": "test-broker",
            "host": "127.0.0.1",
            "port": port,
            "upstreams": upstreams,
        }
    )


@asynccontextmanager
async def running_broker(upstreams: dict[str, dict[str, Any]]) -> AsyncIterator[str]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(config_for(port, upstreams)), log_level="error", lifespan="on")
    )
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
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from irigate.broker import Broker
from tests.helpers import config_for, running_broker, upstream

pytestmark = pytest.mark.asyncio


def echo_processes() -> set[int]:
    marker = str(Path(__file__).parent / "fixtures" / "echo_server.py")
    found: set[int] = set()
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if marker in command:
            found.add(int(entry.name))
    return found


async def wait_for_baseline(baseline: set[int]) -> None:
    for _ in range(300):
        if echo_processes() <= baseline:
            return
        await asyncio.sleep(0.02)
    assert echo_processes() <= baseline


async def test_shutdown_bounds_active_call_and_cleans_processes() -> None:
    baseline = echo_processes()
    broker = Broker(config_for(8765, {"echo": upstream(timeout=10)}))
    await broker.start()
    call = asyncio.create_task(
        broker.call_tool(
            "echo__repeat", {"value": "drain", "delay_seconds": 30}, "session"
        )
    )
    await asyncio.sleep(0.05)

    await asyncio.wait_for(broker.close(), timeout=6)
    result = await call
    await wait_for_baseline(baseline)

    assert result.isError is True
    assert echo_processes() <= baseline


async def test_client_disconnect_then_repeated_startup_shutdown_leaves_no_orphans() -> None:
    baseline = echo_processes()
    for _ in range(3):
        async with running_broker({"echo": upstream()}) as _url:
            pass
        await wait_for_baseline(baseline)

    assert echo_processes() <= baseline

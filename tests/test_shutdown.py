from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from irigate.broker import Broker
from tests.helpers import config_for, running_broker, upstream
from tests.test_qualification import context7

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


async def wait_for_idle_shutdown(worker: object) -> None:
    for _ in range(200):
        if not getattr(worker, "is_running"):
            return
        await asyncio.sleep(0.01)
    assert not getattr(worker, "is_running")


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


async def test_isolated_worker_restarts_after_its_idle_timeout() -> None:
    broker = Broker(config_for(8765, {"echo": upstream(idle_timeout=0.05)}))
    await broker.start()
    try:
        first_result = await broker.call_tool("echo__repeat", {"value": "first"}, "session")
        first_worker = await broker.worker_for("echo", "session")
        await wait_for_idle_shutdown(first_worker)
        assert broker.runtime_snapshot()["upstreams"]["echo"]["live_instances"] == 0

        second_result = await broker.call_tool("echo__repeat", {"value": "second"}, "session")
        second_worker = await broker.worker_for("echo", "session")

        assert first_result.structuredContent == {"value": "first"}
        assert second_result.structuredContent == {"value": "second"}
        assert second_worker is not first_worker
    finally:
        await broker.close()


async def test_shared_worker_restarts_after_its_idle_timeout() -> None:
    definition = context7()
    definition["idle_timeout_seconds"] = 0.05
    broker = Broker(config_for(8765, {"context7": definition}))
    await broker.start()
    try:
        first_worker = await broker.worker_for("context7", "session-a")
        await wait_for_idle_shutdown(first_worker)

        result = await broker.call_tool(
            "context7__resolve-library-id", {"library_name": "idle"}, "session-b"
        )
        second_worker = await broker.worker_for("context7", "session-b")

        assert result.isError is False
        assert second_worker is not first_worker
        assert broker.runtime_snapshot()["upstreams"]["context7"]["live_instances"] == 1
    finally:
        await broker.close()

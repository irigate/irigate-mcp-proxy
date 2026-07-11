from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from irigate.broker import Broker
from tests.helpers import config_for, upstream

pytestmark = pytest.mark.asyncio


async def test_slow_upstream_does_not_delay_fast_upstream() -> None:
    broker = Broker(
        config_for(
            8765,
            {
                "slow": upstream(),
                "fast": upstream(),
            },
        )
    )
    await broker.start()
    try:
        await asyncio.gather(
            broker.worker_for("slow", "session"),
            broker.worker_for("fast", "session"),
        )
        slow = asyncio.create_task(
            broker.call_tool(
                "slow__repeat", {"value": "slow", "delay_seconds": 0.3}, "session"
            )
        )
        await asyncio.sleep(0.03)
        started = time.monotonic()
        fast = await broker.call_tool("fast__repeat", {"value": "fast"}, "session")
        elapsed = time.monotonic() - started
        await slow

        assert fast.structuredContent == {"value": "fast"}
        assert elapsed < 0.2
    finally:
        await broker.close()


@pytest.mark.parametrize(
    ("mode", "minimum", "maximum"),
    [("serial", 0.25, 1.0), ("parallel", 0.0, 0.25)],
)
async def test_concurrency_modes(mode: str, minimum: float, maximum: float) -> None:
    definition = upstream()
    definition["concurrency"] = mode
    broker = Broker(config_for(8765, {"echo": definition}))
    await broker.start()
    try:
        await broker.worker_for("echo", "session")
        started = time.monotonic()
        first, second = await asyncio.gather(
            broker.call_tool(
                "echo__repeat", {"value": "first", "delay_seconds": 0.15}, "session"
            ),
            broker.call_tool(
                "echo__repeat", {"value": "second", "delay_seconds": 0.15}, "session"
            ),
        )
        elapsed = time.monotonic() - started

        assert first.isError is False
        assert second.isError is False
        assert minimum <= elapsed < maximum
    finally:
        await broker.close()


async def test_non_shareable_state_is_not_reused_across_sessions() -> None:
    state_server = Path(__file__).parent / "fixtures" / "state_server.py"
    definition = upstream(args=[str(state_server)])
    broker = Broker(config_for(8765, {"state": definition}))
    await broker.start()
    try:
        await broker.call_tool("state__set_state", {"value": "session-a"}, "session-a")
        result_a = await broker.call_tool("state__get_state", {}, "session-a")
        result_b = await broker.call_tool("state__get_state", {}, "session-b")

        assert result_a.structuredContent == {"value": "session-a"}
        assert result_b.structuredContent == {"value": None}
    finally:
        await broker.close()


async def test_workspace_arguments_are_scoped_to_session_and_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from irigate.selection import parse_selection

    workspace_server = Path(__file__).parent / "fixtures" / "workspace_server.py"
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    definition = upstream(args=[str(workspace_server), "{workspace}"])
    definition["inputs"] = {
        "workspace": {
            "type": "directory",
            "required": True,
            "allowed_roots": [str(tmp_path)],
        }
    }
    config = config_for(8765, {"filesystem": definition})
    selection_a = parse_selection(
        [("upstreams", "filesystem"), ("filesystem.workspace", str(workspace_a))],
        config.upstreams,
    )
    selection_b = parse_selection(
        [("upstreams", "filesystem"), ("filesystem.workspace", str(workspace_b))],
        config.upstreams,
    )
    broker = Broker(config)
    await broker.start()
    try:
        result_a = await broker.call_tool(
            "filesystem__workspace", {}, "session-a", selection_a
        )
        result_b = await broker.call_tool(
            "filesystem__workspace", {}, "session-b", selection_b
        )
        worker_a = await broker.worker_for(
            "filesystem", "session-a", selection_a.inputs
        )
        reused_a = await broker.worker_for(
            "filesystem", "session-a", selection_a.inputs
        )
        worker_b = await broker.worker_for(
            "filesystem", "session-b", selection_b.inputs
        )
        changed_a = await broker.worker_for(
            "filesystem", "session-a", selection_b.inputs
        )

        assert result_a.structuredContent == {"workspace": str(workspace_a)}
        assert result_b.structuredContent == {"workspace": str(workspace_b)}
        assert reused_a is worker_a
        assert worker_b is not worker_a
        assert changed_a is not worker_a
        runtime_output = repr(broker.runtime_snapshot())
        captured_output = capsys.readouterr()
        assert str(workspace_a) not in runtime_output + captured_output.err
        assert str(workspace_b) not in runtime_output + captured_output.err
    finally:
        await broker.close()


async def test_every_shareable_profile_entry_names_its_reviewed_qualifier() -> None:
    from irigate.config import load_config

    root = Path(__file__).resolve().parents[1]
    for profile_name in ("mvp.yaml", "benchmark-heavy.yaml"):
        config = load_config(root / "profiles" / profile_name)
        shareable = {
            key: item.qualifier for key, item in config.upstreams.items() if item.shareable
        }
        assert shareable == {"context7": "context7-readonly-v3"}

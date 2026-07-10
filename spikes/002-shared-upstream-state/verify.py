from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HOST = "127.0.0.1"
PORT = 8766
URL = f"http://{HOST}:{PORT}/mcp"
TRACKED_COMMANDS = ("code-review-graph", "@upstash/context7-mcp", "crash_server.py")


def matching_processes() -> set[int]:
    matches: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(fragment in command for fragment in TRACKED_COMMANDS):
            matches.add(int(entry.name))
    return matches


def wait_ready(process: subprocess.Popen[str], timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"broker exited early ({process.returncode})\n{stdout}\n{stderr}")
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex((HOST, PORT)) == 0:
                return
        time.sleep(0.10)
    raise TimeoutError("sharing broker did not become ready")


def text_value(result: Any) -> str:
    assert not result.isError, result
    assert result.structuredContent is not None, result
    value = result.structuredContent.get("result")
    assert isinstance(value, str), result
    return value


async def call_broker(tool: str, arguments: dict[str, Any]) -> str:
    async with streamable_http_client(URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {item.name for item in listed.tools}
            assert tool in names, f"{tool} not exposed by broker: {sorted(names)}"
            return text_value(await session.call_tool(tool, arguments))


async def verify_stateful_control() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(HERE / "stateful_server.py")])
    async with stdio_client(params) as first_streams:
        async with ClientSession(*first_streams) as first:
            await first.initialize()
            await first.call_tool("set_state", {"value": "client-a-state"})
            shared_result = await first.call_tool("get_state", {})
            assert shared_result.structuredContent == {"value": "client-a-state"}
    async with stdio_client(params) as second_streams:
        async with ClientSession(*second_streams) as second:
            await second.initialize()
            isolated_result = await second.call_tool("get_state", {})
            assert isolated_result.structuredContent == {"value": None}


async def verify_real_upstreams() -> None:
    crg, context7 = await asyncio.gather(
        call_broker("crg__list_graph_stats", {"repo_root": str(ROOT)}),
        call_broker(
            "context7__resolve_library_id",
            {"query": "Find Python documentation for an MCP compatibility probe", "library_name": "Python"},
        ),
    )
    crg_payload = json.loads(crg)
    assert crg_payload["status"] == "ok", crg
    assert "Context7-compatible library ID" in context7, context7

    before_crash = await call_broker("crash__repeat", {"value": "alive"})
    assert "alive" in before_crash
    contained = await call_broker("crash__terminate", {})
    assert contained.startswith("contained:"), contained

    crg_after = await call_broker("crg__list_graph_stats", {"repo_root": str(ROOT)})
    assert json.loads(crg_after)["status"] == "ok"


def main() -> None:
    baseline = matching_processes()
    process = subprocess.Popen(
        [sys.executable, str(HERE / "broker.py")],
        cwd=HERE,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready(process)
        anyio.run(verify_stateful_control)
        anyio.run(verify_real_upstreams)
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError("sharing broker required SIGKILL")

    assert process.returncode in (0, -signal.SIGTERM), (
        f"broker shutdown={process.returncode}\n{stdout}\n{stderr}"
    )
    assert "Application shutdown complete" in stderr, stderr
    deadline = time.monotonic() + 10.0
    remaining = matching_processes() - baseline
    while remaining and time.monotonic() < deadline:
        time.sleep(0.10)
        remaining = matching_processes() - baseline
    assert not remaining, f"orphan upstream processes: {sorted(remaining)}"
    print("VALIDATED: context7 fixed-identity read-only sharing; code-review-graph remains isolated; upstream crash contained")


if __name__ == "__main__":
    main()

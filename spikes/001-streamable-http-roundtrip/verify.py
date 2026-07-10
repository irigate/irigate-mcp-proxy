from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/mcp"


def wait_ready(process: subprocess.Popen[str], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"broker exited early ({process.returncode})\n{stdout}\n{stderr}")
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex((HOST, PORT)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError("broker did not become ready")


async def call_echo(value: str, delay_seconds: float = 0.0) -> dict[str, Any]:
    async with streamable_http_client(URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert [tool.name for tool in tools.tools] == ["echo__repeat"]
            result = await session.call_tool(
                "echo__repeat",
                {"value": value, "delay_seconds": delay_seconds},
            )
            assert not result.isError, result
            assert result.structuredContent is not None
            assert result.structuredContent == {"value": value}, result
            return result.structuredContent


async def verify_roundtrip() -> None:
    assert (await call_echo("roundtrip"))["value"] == "roundtrip"

    first, second = await asyncio.gather(
        call_echo("slow-caller", 0.10),
        call_echo("fast-caller", 0.01),
    )
    assert first["value"] == "slow-caller"
    assert second["value"] == "fast-caller"

    await call_echo("disconnect-before")
    await call_echo("reconnect-after")

    async with streamable_http_client(URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            timed_out = await session.call_tool(
                "echo__repeat",
                {"value": "timeout", "delay_seconds": 1.0},
            )
            assert timed_out.isError

    async with httpx.AsyncClient(timeout=5.0) as client:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "origin-probe", "version": "1"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        remote = await client.post(URL, json=payload, headers={**headers, "Origin": "https://attacker.example"})
        malformed = await client.post(URL, json=payload, headers={**headers, "Origin": "not-an-origin"})
        no_origin = await client.post(URL, json=payload, headers=headers)
        loopback = await client.post(URL, json=payload, headers={**headers, "Origin": f"http://{HOST}:{PORT}"})
        assert remote.status_code == 403, remote.text
        assert malformed.status_code == 403, malformed.text
        assert no_origin.status_code == 200, no_origin.text
        assert loopback.status_code == 200, loopback.text


def main() -> None:
    call_log = HERE / "calls.log"
    call_log.unlink(missing_ok=True)
    env = os.environ.copy()
    env.update({"SPIKE_CALL_LOG": str(call_log), "SPIKE_PYTHON": sys.executable})
    process = subprocess.Popen(
        [sys.executable, str(HERE / "broker.py")],
        cwd=HERE,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready(process)
        anyio.run(verify_roundtrip)
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError("broker required SIGKILL")
        call_log.unlink(missing_ok=True)
    assert process.returncode in (0, -signal.SIGTERM), (
        f"broker shutdown={process.returncode}\n{stdout}\n{stderr}"
    )
    assert "Application shutdown complete" in stderr, stderr
    print("VALIDATED: initialize, tools/list, tools/call, two-client correlation, reconnect, timeout, Origin policy, graceful shutdown")


if __name__ == "__main__":
    main()

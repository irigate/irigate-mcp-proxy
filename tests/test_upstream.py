from __future__ import annotations

import asyncio
import os
import socket
import time
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.exceptions import McpError

from irigate.models import UpstreamConfig
from irigate.upstream import (
    UpstreamError,
    UpstreamLaunchError,
    UpstreamWorker,
    _Call,
    _wsl_windows_environment,
)


def bind_interop_socket(path: Path) -> socket.socket:
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.bind(str(path))
    return endpoint


def test_wsl_windows_environment_selects_newest_live_interop_socket(tmp_path: Path) -> None:
    older = bind_interop_socket(tmp_path / "100_interop")
    newer = bind_interop_socket(tmp_path / "200_interop")
    try:
        os.utime(tmp_path / "100_interop", ns=(1_000_000_000, 1_000_000_000))
        os.utime(tmp_path / "200_interop", ns=(2_000_000_000, 2_000_000_000))
        configured = {"PENCIL_LOG_LEVEL": "info", "WSL_INTEROP": "/stale/endpoint"}

        resolved = _wsl_windows_environment(configured, runtime_dir=tmp_path)

        assert resolved == {
            "PENCIL_LOG_LEVEL": "info",
            "WSL_INTEROP": str(tmp_path / "200_interop"),
        }
        assert configured["WSL_INTEROP"] == "/stale/endpoint"
    finally:
        older.close()
        newer.close()


def test_wsl_windows_environment_ignores_non_socket_entries(tmp_path: Path) -> None:
    (tmp_path / "100_interop").write_text("not a socket", encoding="utf-8")

    with pytest.raises(UpstreamLaunchError, match="restart Irigate"):
        _wsl_windows_environment({}, runtime_dir=tmp_path)


def test_wsl_windows_environment_reports_missing_runtime_directory(tmp_path: Path) -> None:
    with pytest.raises(UpstreamLaunchError, match="WSL Windows interop is unavailable"):
        _wsl_windows_environment({}, runtime_dir=tmp_path / "missing")


@pytest.mark.asyncio
async def test_mcp_response_error_remains_a_tool_error() -> None:
    class ErrorSession:
        async def call_tool(self, tool: str, arguments: dict[str, object]) -> None:
            raise McpError(
                types.ErrorData(
                    code=-32000,
                    message="A file needs to be open in the editor",
                )
            )

    worker = UpstreamWorker(
        "pencil",
        UpstreamConfig.model_validate(
            {
                "command": "pencil",
                "idle_timeout_seconds": 300,
            }
        ),
        {},
    )
    future: asyncio.Future[types.CallToolResult] = asyncio.get_running_loop().create_future()
    request = _Call("get_editor_state", {}, future, time.monotonic())

    await worker._execute_call(ErrorSession(), request)  # type: ignore[arg-type]

    result = future.result()
    assert result.isError is True
    assert result.content == [
        types.TextContent(type="text", text="A file needs to be open in the editor")
    ]


@pytest.mark.asyncio
async def test_mcp_connection_closed_remains_a_transport_failure() -> None:
    class ClosedSession:
        async def call_tool(self, tool: str, arguments: dict[str, object]) -> None:
            raise McpError(types.ErrorData(code=-32000, message="Connection closed"))

    worker = UpstreamWorker(
        "crashed",
        UpstreamConfig.model_validate(
            {
                "command": "fixture",
                "idle_timeout_seconds": 300,
            }
        ),
        {},
    )
    future: asyncio.Future[types.CallToolResult] = asyncio.get_running_loop().create_future()
    request = _Call("terminate", {}, future, time.monotonic())

    await worker._execute_call(ClosedSession(), request)  # type: ignore[arg-type]

    with pytest.raises(UpstreamError, match="call failed"):
        future.result()

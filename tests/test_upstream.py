from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.exceptions import McpError

import irigate.upstream as upstream_module
from irigate.models import UpstreamConfig
from irigate.upstream import (
    UpstreamError,
    UpstreamLaunchError,
    UpstreamWorker,
    _Call,
    _render_upstream_args,
    _transform_wsl_windows_paths,
    _wsl_windows_path,
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


def test_wsl_windows_path_converts_posix_paths_and_preserves_windows_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wsl_windows_path.cache_clear()
    monkeypatch.setattr(
        upstream_module.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments,
            0,
            stdout="C:\\Users\\example\\design.pen\r\n",
            stderr="",
        ),
    )

    assert _wsl_windows_path("/mnt/c/Users/example/design.pen") == (
        "C:\\Users\\example\\design.pen"
    )
    assert _wsl_windows_path("C:\\Users\\example\\design.pen") == (
        "C:\\Users\\example\\design.pen"
    )
    assert _wsl_windows_path("\\\\server\\share\\design.pen") == (
        "\\\\server\\share\\design.pen"
    )
    assert _wsl_windows_path("/C:/Users/example/design.pen") == (
        "C:\\Users\\example\\design.pen"
    )


def test_transforms_only_configured_wsl_path_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        upstream_module,
        "_wsl_windows_path",
        lambda value: f"WINDOWS:{value}",
    )
    arguments = {
        "filePath": "/home/user/design.pen",
        "output": {"directory": "/mnt/c/Users/user/export"},
        "alreadyWindows": "C:\\Users\\user\\design.pen",
        "prompt": "/home/user is prose here",
        "empty": "",
    }

    transformed = _transform_wsl_windows_paths(
        arguments,
        ("/filePath", "/output/directory", "/alreadyWindows", "/empty", "/missing"),
    )

    assert transformed == {
        "filePath": "WINDOWS:/home/user/design.pen",
        "output": {"directory": "WINDOWS:/mnt/c/Users/user/export"},
        "alreadyWindows": "C:\\Users\\user\\design.pen",
        "prompt": "/home/user is prose here",
        "empty": "",
    }
    assert arguments["filePath"] == "/home/user/design.pen"
    assert arguments["output"] == {"directory": "/mnt/c/Users/user/export"}


def test_wsl_path_arguments_reject_configured_non_string_value() -> None:
    with pytest.raises(UpstreamError, match="must reference a string"):
        _transform_wsl_windows_paths({"filePath": 42}, ("/filePath",))


def test_wsl_windows_workspace_argument_is_rendered_as_windows_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        upstream_module,
        "_wsl_windows_path",
        lambda value: f"WINDOWS:{value}",
    )
    config = UpstreamConfig.model_validate(
        {
            "command": "workspace.exe",
            "args": ["--workspace", "{workspace}"],
            "execution": "wsl-windows",
            "inputs": {
                "workspace": {
                    "type": "directory",
                    "required": True,
                    "allowed_roots": ["/home/user"],
                }
            },
            "idle_timeout_seconds": 300,
        }
    )

    rendered = _render_upstream_args(config, {"workspace": "/home/user/project"})

    assert rendered == ["--workspace", "WINDOWS:/home/user/project"]
    assert config.args == ("--workspace", "{workspace}")


@pytest.mark.asyncio
async def test_worker_transforms_wsl_windows_paths_at_upstream_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingSession:
        arguments: dict[str, object] | None = None

        async def call_tool(
            self, tool: str, arguments: dict[str, object]
        ) -> types.CallToolResult:
            self.arguments = arguments
            return types.CallToolResult(content=[], isError=False)

    monkeypatch.setattr(
        upstream_module,
        "_wsl_windows_path",
        lambda value: f"WINDOWS:{value}",
    )
    worker = UpstreamWorker(
        "pencil",
        UpstreamConfig.model_validate(
            {
                "command": "pencil.exe",
                "execution": "wsl-windows",
                "wsl_path_arguments": {
                    "*": ["/filePath"],
                    "export_html": ["/outputPath"],
                },
                "idle_timeout_seconds": 300,
            }
        ),
        {},
    )
    arguments = {
        "filePath": "/home/user/design.pen",
        "outputPath": "/mnt/c/Users/user/export/index.html",
    }
    session = RecordingSession()
    future: asyncio.Future[types.CallToolResult] = asyncio.get_running_loop().create_future()
    request = _Call("export_html", arguments, future, time.monotonic())

    await worker._execute_call(session, request)  # type: ignore[arg-type]

    assert session.arguments == {
        "filePath": "WINDOWS:/home/user/design.pen",
        "outputPath": "WINDOWS:/mnt/c/Users/user/export/index.html",
    }
    assert arguments == {
        "filePath": "/home/user/design.pen",
        "outputPath": "/mnt/c/Users/user/export/index.html",
    }


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

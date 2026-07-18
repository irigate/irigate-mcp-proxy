from __future__ import annotations

import json
import select
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import types

from irigate.broker import Broker
from irigate.logs import MCP_LOG_KEEP_FILES, McpCallLog, iter_log, log_directory
from tests.helpers import config_for, upstream


def write_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "\n".join(
            [
                "name: logs-test",
                "host: 127.0.0.1",
                "port: 8765",
                f"runtime_log_path: {tmp_path / 'configured-logs'}",
                "upstreams:",
                "  dormant:",
                "    transport: stdio",
                "    command: dormant-command-is-not-started",
                "    args: []",
                "    env: {}",
                "    shareable: false",
                "    concurrency: serial",
                "    call_timeout_seconds: 5",
                "    idle_timeout_seconds: 60",
            ]
        ),
        encoding="utf-8",
    )
    return profile


def emit_record(call_log: McpCallLog, value: str) -> None:
    call_log.emit(
        tool="echo__repeat",
        arguments={"value": value},
        agent="test",
        duration_seconds=0.001,
        result=types.CallToolResult(
            content=[types.TextContent(type="text", text=value)], isError=False
        ),
    )


def test_default_log_directory_uses_profile_under_local_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert log_directory("logs-test") == tmp_path / ".local/log/irigate/logs-test"


def test_configured_log_directory_is_used_exactly(tmp_path: Path) -> None:
    configured = tmp_path / "custom-logs"

    assert log_directory("logs-test", configured) == configured


def test_each_start_creates_a_private_log_and_rotates_old_files(tmp_path: Path) -> None:
    directory = tmp_path / "rotation-logs"
    paths = [
        McpCallLog.start("rotation-test", directory=directory).path
        for _ in range(MCP_LOG_KEEP_FILES + 2)
    ]

    remaining = tuple(directory.glob("rotation-test-*.jsonl"))
    assert len(remaining) == MCP_LOG_KEEP_FILES
    assert not paths[0].exists()
    assert not paths[1].exists()
    assert paths[-1].exists()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in remaining)


@pytest.mark.asyncio
async def test_log_records_complete_tool_calls_and_responses(tmp_path: Path) -> None:
    call_log = McpCallLog.start("broker-test", directory=tmp_path / "logs")
    broker = Broker(
        config_for(8765, {"echo": upstream()}),
        call_log=call_log,
    )
    await broker.start()
    try:
        success = await broker.call_tool(
            "echo__repeat", {"value": "logged-payload"}, "client", agent="codex"
        )
        rejected = await broker.call_tool(
            "echo__missing", {"value": "rejected-payload"}, "client", agent="codex"
        )
    finally:
        await broker.close()

    assert success.isError is False
    assert rejected.isError is True
    records = [json.loads(line) for line in call_log.path.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["agent"] == "codex"
    assert records[0]["request"] == {
        "method": "tools/call",
        "params": {
            "name": "echo__repeat",
            "arguments": {"value": "logged-payload"},
        },
    }
    assert records[0]["response"]["result"]["isError"] is False
    assert "logged-payload" in json.dumps(records[0]["response"])
    assert records[1]["request"]["params"]["arguments"] == {
        "value": "rejected-payload"
    }
    assert records[1]["response"]["result"]["isError"] is True


@pytest.mark.asyncio
async def test_log_append_failure_does_not_replace_tool_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    call_log = McpCallLog.start("broker-test", directory=tmp_path / "logs")

    def fail_emit(**_kwargs: object) -> None:
        raise OSError("synthetic log failure")

    monkeypatch.setattr(call_log, "emit", fail_emit)
    broker = Broker(config_for(8765, {"echo": upstream()}), call_log=call_log)
    await broker.start()
    try:
        result = await broker.call_tool("echo__repeat", {"value": "completed"}, "client")
    finally:
        await broker.close()

    assert result.isError is False
    assert "MCP payload log write failed" in caplog.text


def test_cli_logs_prints_latest_profile_log(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    directory = tmp_path / "configured-logs"
    old_log = McpCallLog.start("logs-test", directory=directory)
    emit_record(old_log, "old")
    current_log = McpCallLog.start("logs-test", directory=directory)
    emit_record(current_log, "current")

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "logs", "--config", str(profile)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["request"]["params"]["arguments"] == {"value": "current"}


def test_cli_logs_follow_prints_appended_records_live(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    call_log = McpCallLog.start("logs-test", directory=tmp_path / "configured-logs")
    emit_record(call_log, "first")
    process = subprocess.Popen(
        [sys.executable, "-m", "irigate", "logs", "-f", "--config", str(profile)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    try:
        assert select.select([process.stdout], [], [], 5)[0]
        assert json.loads(process.stdout.readline())["request"]["params"]["arguments"] == {
            "value": "first"
        }
        emit_record(call_log, "second")
        assert select.select([process.stdout], [], [], 5)[0]
        assert json.loads(process.stdout.readline())["request"]["params"]["arguments"] == {
            "value": "second"
        }
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_cli_logs_reports_missing_log(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "logs", "--config", str(profile)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "logs error: no MCP log files for profile 'logs-test'" in result.stderr


def test_follow_iterator_yields_appended_lines(tmp_path: Path) -> None:
    path = tmp_path / "current.jsonl"
    path.write_text("first\n", encoding="utf-8")
    lines = iter_log(path, follow=True)

    assert next(lines) == "first\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("second\n")
        stream.flush()
    assert next(lines) == "second\n"
    lines.close()

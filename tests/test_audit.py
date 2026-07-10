from __future__ import annotations

import json
from pathlib import Path

import pytest

from irigate.broker import Broker
from tests.helpers import config_for, upstream

pytestmark = pytest.mark.asyncio


def audit_records(captured: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in captured.splitlines() if line.startswith("{")]


async def test_audits_success_without_payload_or_result(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = upstream()
    definition["env"] = {"AUDIT_SENTINEL": "${IRIGATE_AUDIT_SECRET}"}
    monkeypatch.setenv("IRIGATE_AUDIT_SECRET", "sentinel-environment-secret")
    broker = Broker(config_for(8765, {"echo": definition}))
    await broker.start()
    try:
        result = await broker.call_tool(
            "echo__repeat", {"value": "sentinel-argument-and-result"}, "client"
        )
        assert result.isError is False
    finally:
        await broker.close()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    records = audit_records(captured.err)
    assert records[-1]["outcome"] == "success"
    assert records[-1]["upstream"] == "echo"
    assert records[-1]["tool"] == "repeat"
    assert "sentinel-argument-and-result" not in combined
    assert "sentinel-environment-secret" not in combined


async def test_audits_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    broker = Broker(config_for(8765, {"echo": upstream(timeout=0.05)}))
    await broker.start()
    try:
        result = await broker.call_tool(
            "echo__repeat", {"value": "slow", "delay_seconds": 0.5}, "client"
        )
        assert result.isError is True
    finally:
        await broker.close()

    assert audit_records(capsys.readouterr().err)[-1]["outcome"] == "timeout"


async def test_audits_upstream_error(capsys: pytest.CaptureFixture[str]) -> None:
    broker = Broker(config_for(8765, {"echo": upstream()}))
    await broker.start()
    try:
        result = await broker.call_tool("echo__terminate", {}, "client")
        assert result.isError is True
    finally:
        await broker.close()

    assert audit_records(capsys.readouterr().err)[-1]["outcome"] == "upstream_error"


@pytest.mark.parametrize("name", ["missing__repeat", "echo__missing"])
async def test_audits_invalid_tool(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    broker = Broker(config_for(8765, {"echo": upstream()}))
    await broker.start()
    try:
        result = await broker.call_tool(name, {}, "client")
        assert result.isError is True
    finally:
        await broker.close()

    assert audit_records(capsys.readouterr().err)[-1]["outcome"] == "invalid_tool"


async def test_audits_call_rejected_during_shutdown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    broker = Broker(config_for(8765, {"echo": upstream()}))
    await broker.start()
    await broker.close()

    result = await broker.call_tool("echo__repeat", {"value": "after-close"}, "client")
    assert result.isError is True
    assert audit_records(capsys.readouterr().err)[-1]["outcome"] == "shutdown"


async def test_each_completed_call_emits_exactly_one_record(
    capsys: pytest.CaptureFixture[str],
) -> None:
    broker = Broker(config_for(8765, {"echo": upstream()}))
    await broker.start()
    try:
        await broker.call_tool("echo__repeat", {"value": "one"}, "client")
        await broker.call_tool("echo__repeat", {"value": "two"}, "client")
    finally:
        await broker.close()

    records = audit_records(capsys.readouterr().err)
    assert [record["outcome"] for record in records] == ["success", "success"]
    assert all(set(record) == {"timestamp", "upstream", "tool", "outcome", "duration_ms"} for record in records)

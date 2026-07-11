from __future__ import annotations

import json
from pathlib import Path

import pytest

from irigate.broker import Broker
from tests.helpers import config_for, upstream
from tests.test_qualification import CONTEXT7_SERVER, context7

pytestmark = pytest.mark.asyncio


def with_report(config, path: Path):
    return config.model_copy(update={"runtime_report_path": path})


async def test_one_client_shared_run_reports_insufficient_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = context7()
    definition["env"] = {"UPSTREAM_SENTINEL": "${IRIGATE_PHASE4_SENTINEL}"}
    monkeypatch.setenv("IRIGATE_PHASE4_SENTINEL", "sentinel-environment-value")
    config = with_report(
        config_for(8765, {"context7": definition}), tmp_path / "report.json"
    )
    broker = Broker(config)
    await broker.start()
    try:
        result = await broker.call_tool(
            "context7__resolve-library-id", {"library_name": "sentinel-payload"}, "client-a"
        )
        assert result.isError is False
    finally:
        await broker.close()

    report = json.loads(config.runtime_report_path.read_text())
    assert report["summary"]["evidence"] == "insufficient_evidence"
    assert report["summary"]["avoided_instances"] == 0
    report_text = config.runtime_report_path.read_text()
    assert "sentinel-payload" not in report_text
    assert "sentinel-environment-value" not in report_text


async def test_multi_client_shared_run_reports_avoided_instances(tmp_path: Path) -> None:
    config = with_report(config_for(8765, {"context7": context7()}), tmp_path / "report.json")
    broker = Broker(config)
    await broker.start()
    try:
        for client in ("client-a", "client-b", "client-c"):
            await broker.call_tool(
                "context7__query-docs",
                {"library_id": "/test/library"},
                client,
                agent=client,
            )
    finally:
        await broker.close()

    report = json.loads(config.runtime_report_path.read_text())
    upstream_report = report["upstreams"]["context7"]
    assert report["summary"] == {"evidence": "qualified", "avoided_instances": 2}
    assert upstream_report["logical_bindings"] == 3
    assert upstream_report["spawns"] >= 1
    assert upstream_report["reuse_hits"] >= 2
    assert report["schema_version"] == 2
    assert report["agents"] == {
        "client-a": {"context7": {"calls": 1, "failures": 0}},
        "client-b": {"context7": {"calls": 1, "failures": 0}},
        "client-c": {"context7": {"calls": 1, "failures": 0}},
    }


async def test_agent_failure_is_counted_without_recording_payload(tmp_path: Path) -> None:
    config = with_report(config_for(8765, {"echo": upstream()}), tmp_path / "report.json")
    broker = Broker(config)
    await broker.start()
    try:
        result = await broker.call_tool(
            "echo__repeat",
            {"missing": "sentinel-agent-payload"},
            "session",
            agent="codex",
        )
        assert result.isError is True
    finally:
        await broker.close()

    assert config.runtime_report_path is not None
    report_text = config.runtime_report_path.read_text()
    report = json.loads(report_text)
    assert report["agents"] == {"codex": {"echo": {"calls": 1, "failures": 1}}}
    assert "sentinel-agent-payload" not in report_text


async def test_isolated_run_never_claims_consolidation(tmp_path: Path) -> None:
    config = with_report(config_for(8765, {"echo": upstream()}), tmp_path / "report.json")
    broker = Broker(config)
    await broker.start()
    try:
        await broker.call_tool("echo__repeat", {"value": "a"}, "client-a")
        await broker.call_tool("echo__repeat", {"value": "b"}, "client-b")
    finally:
        await broker.close()

    report = json.loads(config.runtime_report_path.read_text())
    assert report["summary"]["avoided_instances"] == 0
    assert report["upstreams"]["echo"]["effective_mode"] == "isolated"


async def test_atomic_report_has_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "report.json"
    config = with_report(config_for(8765, {"echo": upstream()}), path)
    broker = Broker(config)
    await broker.start()
    try:
        await broker.call_tool("echo__repeat", {"value": "safe"}, "client")
    finally:
        await broker.close()

    assert path.exists()
    assert list(path.parent.glob("*.tmp")) == []


async def test_failure_threshold_degrades_shared_upstream(tmp_path: Path) -> None:
    definition = context7()
    definition["failure_threshold"] = 1
    definition["crash_threshold"] = 1
    config = with_report(config_for(8765, {"context7": definition}), tmp_path / "report.json")
    broker = Broker(config)
    await broker.start()
    try:
        original = await broker.worker_for("context7", "client-a")
        failed = await broker.call_tool("context7__terminate", {}, "client-a")
        replacement = await broker.worker_for("context7", "client-b")
        assert failed.isError is True
        assert replacement is not original
    finally:
        await broker.close()

    report = json.loads(config.runtime_report_path.read_text())
    assert report["upstreams"]["context7"]["effective_mode"] == "degraded"
    assert report["upstreams"]["context7"]["crashes"] >= 1


async def test_report_contains_duration_counters(tmp_path: Path) -> None:
    config = with_report(config_for(8765, {"echo": upstream()}), tmp_path / "report.json")
    broker = Broker(config)
    await broker.start()
    try:
        await broker.call_tool("echo__repeat", {"value": "duration"}, "client")
    finally:
        await broker.close()

    upstream_report = json.loads(config.runtime_report_path.read_text())["upstreams"]["echo"]
    for field in ("startup_duration", "queue_duration", "call_duration"):
        assert upstream_report[field]["count"] >= 1
        assert upstream_report[field]["total_ms"] >= 0

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from irigate.broker import Broker, BrokerInitializationError
from irigate.models import BrokerConfig, UpstreamConfig
from irigate.qualification import GENERIC_CHECKS, qualify_config, qualify_upstream
from tests.helpers import config_for, upstream

pytestmark = pytest.mark.asyncio
CONTEXT7_SERVER = Path(__file__).parent / "fixtures" / "context7_server.py"


def context7(*, timeout: float = 2.0) -> dict[str, object]:
    return upstream(
        args=[str(CONTEXT7_SERVER)],
        shareable=True,
        qualifier="context7-readonly-v3",
        timeout=timeout,
    )


async def test_qualifier_rejects_wrong_upstream_key() -> None:
    upstream_config = UpstreamConfig.model_validate(context7())
    result = await qualify_upstream("echo", upstream_config, {})

    assert result.admitted is False
    assert result.reason == "qualifier does not support upstream key"


async def test_profile_rejects_qualifier_claimed_by_wrong_upstream_key() -> None:
    with pytest.raises(ValueError, match="supports upstream key 'context7'"):
        config_for(8765, {"echo": context7()})


async def test_generic_checks_and_behavioral_probe_admit_context7() -> None:
    config = config_for(8765, {"context7": context7()})
    result = await qualify_upstream("context7", config.upstreams["context7"], {})

    assert result.admitted is True
    assert set(result.checks) == set(GENERIC_CHECKS)
    assert all(result.checks.values())
    assert result.behavioral_checks == {"reviewed_tool_surface": True}


async def test_default_startup_downgrades_failed_sharing() -> None:
    definition = context7()
    definition["args"] = [str(Path(__file__).parent / "fixtures" / "echo_server.py")]
    broker = Broker(config_for(8765, {"context7": definition}))
    await broker.start()
    try:
        first = await broker.worker_for("context7", "session-a")
        second = await broker.worker_for("context7", "session-b")
        assert first is not second
        assert broker.runtime_snapshot()["upstreams"]["context7"]["effective_mode"] == "isolated"
    finally:
        await broker.close()


async def test_strict_startup_rejects_failed_sharing() -> None:
    definition = context7()
    definition["args"] = [str(Path(__file__).parent / "fixtures" / "echo_server.py")]
    broker = Broker(
        config_for(8765, {"context7": definition}), require_qualified_sharing=True
    )
    with pytest.raises(BrokerInitializationError, match="failed qualification"):
        await broker.start()
    await broker.close()


async def test_qualify_config_reports_each_requested_shared_upstream() -> None:
    config = config_for(8765, {"context7": context7(), "isolated": upstream()})
    results = await qualify_config(config)
    assert list(results) == ["context7"]
    assert results["context7"].admitted is True


async def test_qualify_cli_returns_metadata_without_environment_values(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "\n".join(
            [
                "name: qualify-test",
                "host: 127.0.0.1",
                "port: 8765",
                "upstreams:",
                "  context7:",
                "    transport: stdio",
                f"    command: {sys.executable}",
                f"    args: [{CONTEXT7_SERVER}]",
                "    env: {}",
                "    shareable: true",
                "    qualifier: context7-readonly-v3",
                "    concurrency: serial",
                "    call_timeout_seconds: 2",
                "    idle_timeout_seconds: 60",
            ]
        )
    )
    env = os.environ.copy()
    env["IRIGATE_SENTINEL"] = "must-not-appear"
    completed = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "irigate", "qualify", "--config", str(profile)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "context7=qualified" in completed.stdout
    assert "must-not-appear" not in completed.stdout + completed.stderr

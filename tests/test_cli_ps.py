from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def write_profile(tmp_path: Path, report_path: Path) -> Path:
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "\n".join(
            [
                "name: ps-test",
                "host: 127.0.0.1",
                "port: 8765",
                f"runtime_report_path: {report_path}",
                "upstreams:",
                "  graph:",
                "    transport: stdio",
                "    command: missing-command-is-not-started",
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


def runtime_report() -> dict[str, object]:
    return {
        "schema_version": 3,
        "profile": "ps-test",
        "upstreams": {
            "graph": {
                "effective_mode": "shared",
                "live_instances": 1,
                "call_duration": {"count": 5, "total_ms": 42.0},
                "failures": 1,
                "activity_state": "idle",
                "active_calls": 0,
                "idle_since": (datetime.now(timezone.utc) - timedelta(seconds=12)).isoformat(),
                "idle_timeout_seconds": 60,
            }
        },
        "agents": {
            "codex": {"graph": {"calls": 3, "failures": 1}},
            "hermes": {"graph": {"calls": 2, "failures": 0}},
        },
        "summary": {"evidence": "qualified", "avoided_instances": 1},
    }


def test_cli_ps_prints_upstream_agent_usage(tmp_path: Path) -> None:
    report_path = tmp_path / "runtime.json"
    report_path.write_text(json.dumps(runtime_report()), encoding="utf-8")
    profile = write_profile(tmp_path, report_path)

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "ps", "--config", str(profile)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == [
        "UPSTREAM",
        "MODE",
        "INSTANCES",
        "STATE",
        "IDLE_FOR",
        "IDLE_TIMEOUT",
        "AGENT",
        "CALLS",
        "FAILURES",
    ]
    codex = lines[1].split()
    hermes = lines[2].split()
    assert codex[:4] == ["graph", "shared", "1", "idle"]
    assert re.fullmatch(r"1[2-9]s", codex[4])
    assert codex[5:] == ["1m00s", "codex", "3", "1"]
    assert hermes[:4] == ["graph", "shared", "1", "idle"]
    assert re.fullmatch(r"1[2-9]s", hermes[4])
    assert hermes[5:] == ["1m00s", "hermes", "2", "0"]


def test_cli_ps_json_preserves_machine_readable_report(tmp_path: Path) -> None:
    report = runtime_report()
    report_path = tmp_path / "runtime.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    profile = write_profile(tmp_path, report_path)

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "ps", "--config", str(profile), "--json"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == report


def test_cli_ps_reports_missing_runtime_report(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, tmp_path / "missing.json")

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "ps", "--config", str(profile)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "runtime report error: cannot read runtime report" in result.stderr

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "doctor_schema_server.py"
requires_wsl_interop = pytest.mark.skipif(
    not any(path.is_socket() for path in Path("/run/WSL").glob("*_interop")),
    reason="requires a live WSL interop socket",
)


def write_profile(tmp_path: Path, *, execution: str = "wsl-windows") -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "doctor-cli",
                "host": "127.0.0.1",
                "port": 8765,
                "runtime_report_path": str(tmp_path / "runtime-report.json"),
                "upstreams": {
                    "fixture": {
                        "command": sys.executable,
                        "args": [str(FIXTURE)],
                        "execution": execution,
                        "env": {},
                        "shareable": False,
                        "concurrency": "serial",
                        "call_timeout_seconds": 5,
                        "idle_timeout_seconds": 60,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def run_doctor(profile: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "irigate", "doctor", "--config", str(profile), *args],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )


@requires_wsl_interop
def test_doctor_reports_schema_derived_wsl_path_arguments_without_writing(
    tmp_path: Path,
) -> None:
    profile = write_profile(tmp_path)
    original = profile.read_text(encoding="utf-8")
    report_path = tmp_path / "runtime-report.json"
    serving_report = '{"instance_id":"serving-sentinel"}\n'
    report_path.write_text(serving_report, encoding="utf-8")

    result = run_doctor(profile, "--json")

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report == {
        "profile": "doctor-cli",
        "config_path": str(profile.resolve()),
        "status": "repair-needed",
        "upstreams": [
            {
                "name": "fixture",
                "status": "repair-needed",
                "discovered": {
                    "export_html": ["/filePath", "/outputPath"],
                    "export_nodes": ["/filePath", "/outputDir"],
                },
                "configured": {},
                "recommended": {
                    "export_html": ["/filePath", "/outputPath"],
                    "export_nodes": ["/filePath", "/outputDir"],
                },
            }
        ],
    }
    assert profile.read_text(encoding="utf-8") == original
    assert report_path.read_text(encoding="utf-8") == serving_report


@requires_wsl_interop
def test_doctor_apply_repairs_profile_and_second_run_is_healthy(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)

    applied = run_doctor(profile, "--apply")

    assert applied.returncode == 0, applied.stderr
    assert "fixture=repaired" in applied.stdout
    assert "backup=" in applied.stdout
    configured = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert configured["upstreams"]["fixture"]["wsl_path_arguments"] == {
        "export_html": ["/filePath", "/outputPath"],
        "export_nodes": ["/filePath", "/outputDir"],
    }

    healthy = run_doctor(profile, "--json")
    assert healthy.returncode == 0, healthy.stderr
    assert json.loads(healthy.stdout)["status"] == "healthy"


def test_doctor_reports_no_applicable_upstreams(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, execution="native")

    result = run_doctor(profile, "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "not-applicable"

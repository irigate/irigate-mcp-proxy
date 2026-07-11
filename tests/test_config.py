from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from irigate.config import ConfigurationError, load_config


VALID_PROFILE = """\
name: test-profile
host: 127.0.0.1
port: 8765
runtime_report_path: .irigate/report.json
upstreams:
  context7:
    transport: stdio
    command: npx
    args: [-y, '@upstash/context7-mcp']
    env:
      CONTEXT7_API_KEY: ${TEST_CONTEXT7_API_KEY}
    shareable: true
    qualifier: context7-readonly-v3
    concurrency: serial
    call_timeout_seconds: 30
    idle_timeout_seconds: 300
  echo:
    transport: stdio
    command: python3
    args: [-m, echo_server]
    env: {}
    shareable: false
    concurrency: parallel
    call_timeout_seconds: 5
    idle_timeout_seconds: 60
"""


def write_profile(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_valid_profile_and_resolves_environment_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_CONTEXT7_API_KEY", "synthetic-secret-value")

    config = load_config(write_profile(tmp_path, VALID_PROFILE))

    assert config.name == "test-profile"
    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.upstreams["context7"].shareable is True
    assert config.upstreams["context7"].idle_timeout_seconds == 300
    assert config.environment_names == frozenset({"TEST_CONTEXT7_API_KEY"})
    assert config.resolve_environment()["context7"] == {
        "CONTEXT7_API_KEY": "synthetic-secret-value"
    }


def test_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace("port: 8765", "port: 8765\nport: 9000")

    with pytest.raises(ConfigurationError, match=r"duplicate key 'port'"):
        load_config(write_profile(tmp_path, profile))


@pytest.mark.parametrize("command", ["", "   ", "python -m echo_server"])
def test_rejects_invalid_commands(tmp_path: Path, command: str) -> None:
    profile = VALID_PROFILE.replace("command: python3", f"command: '{command}'")

    with pytest.raises(ConfigurationError, match="command"):
        load_config(write_profile(tmp_path, profile))


def test_reports_missing_environment_names_without_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEST_CONTEXT7_API_KEY", raising=False)

    config = load_config(write_profile(tmp_path, VALID_PROFILE))
    with pytest.raises(ConfigurationError) as exc_info:
        config.resolve_environment()

    message = str(exc_info.value)
    assert message == "missing environment references: TEST_CONTEXT7_API_KEY"
    assert "synthetic-secret-value" not in message


def test_rejects_literal_environment_values(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace(
        "${TEST_CONTEXT7_API_KEY}", "literal-secret-must-not-be-accepted"
    )

    with pytest.raises(ConfigurationError, match="environment reference"):
        load_config(write_profile(tmp_path, profile))


def test_rejects_environment_references_in_arguments(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace(
        "args: [-m, echo_server]", "args: [-m, echo_server, '${TEST_CONTEXT7_API_KEY}']"
    )

    with pytest.raises(ConfigurationError, match="arguments must not contain"):
        load_config(write_profile(tmp_path, profile))


@pytest.mark.parametrize("transport", ["sse", "streamable-http", "http"])
def test_rejects_unsupported_upstream_transports(tmp_path: Path, transport: str) -> None:
    profile = VALID_PROFILE.replace("transport: stdio", f"transport: {transport}", 1)

    with pytest.raises(ConfigurationError, match="transport"):
        load_config(write_profile(tmp_path, profile))


def test_rejects_unknown_fields(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace("port: 8765", "port: 8765\nremote_access: true")

    with pytest.raises(ConfigurationError, match="remote_access"):
        load_config(write_profile(tmp_path, profile))


@pytest.mark.parametrize("value", ["0", "-1", "86401"])
def test_rejects_invalid_idle_timeout(tmp_path: Path, value: str) -> None:
    profile = VALID_PROFILE.replace(
        "idle_timeout_seconds: 60", f"idle_timeout_seconds: {value}"
    )

    with pytest.raises(ConfigurationError, match="idle_timeout_seconds"):
        load_config(write_profile(tmp_path, profile))


def test_requires_idle_timeout(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace("    idle_timeout_seconds: 60\n", "")

    with pytest.raises(ConfigurationError, match="idle_timeout_seconds"):
        load_config(write_profile(tmp_path, profile))


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.test"])
def test_rejects_non_loopback_hosts(tmp_path: Path, host: str) -> None:
    profile = VALID_PROFILE.replace("host: 127.0.0.1", f"host: {host}")

    with pytest.raises(ConfigurationError, match="loopback"):
        load_config(write_profile(tmp_path, profile))


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_accepts_loopback_hosts(
    tmp_path: Path, host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_CONTEXT7_API_KEY", "synthetic")
    profile = VALID_PROFILE.replace("host: 127.0.0.1", f"host: '{host}'")

    assert load_config(write_profile(tmp_path, profile)).host == host


def test_rejects_shareable_without_qualifier(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace("    qualifier: context7-readonly-v3\n", "")

    with pytest.raises(ConfigurationError, match="registered qualifier"):
        load_config(write_profile(tmp_path, profile))


def test_rejects_unknown_shareability_qualifier(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace(
        "qualifier: context7-readonly-v3", "qualifier: unreviewed-upstream"
    )

    with pytest.raises(ConfigurationError, match="registered qualifier"):
        load_config(write_profile(tmp_path, profile))


def test_cli_check_prints_metadata_without_environment_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = write_profile(tmp_path, VALID_PROFILE)
    env = os.environ.copy()
    env["TEST_CONTEXT7_API_KEY"] = "must-not-appear-in-cli-output"

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "--config", str(profile), "--check"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "profile=test-profile" in result.stdout
    assert "upstreams=context7,echo" in result.stdout
    assert "environment=TEST_CONTEXT7_API_KEY" in result.stdout
    assert "must-not-appear-in-cli-output" not in result.stdout + result.stderr


def test_cli_tools_lists_namespaced_tools_from_profile(tmp_path: Path) -> None:
    echo_server = Path(__file__).parent / "fixtures" / "echo_server.py"
    profile = write_profile(
        tmp_path,
        "\n".join(
            [
                "name: tool-list",
                "host: 127.0.0.1",
                "port: 8765",
                "upstreams:",
                "  echo:",
                "    transport: stdio",
                f"    command: {sys.executable}",
                f"    args: [{echo_server}]",
                "    env: {}",
                "    shareable: false",
                "    concurrency: serial",
                "    call_timeout_seconds: 5",
                "    idle_timeout_seconds: 60",
            ]
        ),
    )

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "tools", "--config", str(profile)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["echo__repeat", "echo__terminate"]


def test_cli_exits_nonzero_on_validation_error(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, VALID_PROFILE.replace("host: 127.0.0.1", "host: 0.0.0.0"))

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "--config", str(profile), "--check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "loopback" in result.stderr
    assert "synthetic-secret-value" not in result.stderr

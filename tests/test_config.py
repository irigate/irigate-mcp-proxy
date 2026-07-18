from __future__ import annotations

import json
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


def workspace_profile(
    allowed_roots: list[str],
    *,
    args: str = "[-m, echo_server, '{workspace}']",
    input_name: str = "workspace",
    input_type: str = "directory",
    required: str = "true",
) -> str:
    roots = "\n".join(f"        - {json.dumps(root)}" for root in allowed_roots)
    return VALID_PROFILE.replace("args: [-m, echo_server]", f"args: {args}") + (
        f"    inputs:\n"
        f"      {input_name}:\n"
        f"        type: {input_type}\n"
        f"        required: {required}\n"
        f"        allowed_roots:\n{roots}\n"
    )


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


def test_relative_runtime_report_path_is_anchored_to_profile_directory(
    tmp_path: Path,
) -> None:
    config = load_config(write_profile(tmp_path, VALID_PROFILE))

    assert config.runtime_report_path == (tmp_path / ".irigate/report.json").resolve()


def test_absolute_runtime_report_path_is_preserved(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace(
        "runtime_report_path: .irigate/report.json",
        "runtime_report_path: /var/log/irigate/runtime.json",
    )

    config = load_config(write_profile(tmp_path, profile))

    assert config.runtime_report_path == Path("/var/log/irigate/runtime.json")


def test_missing_runtime_report_path_uses_xdg_state_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    profile = "\n".join(
        line
        for line in VALID_PROFILE.splitlines()
        if not line.startswith("runtime_report_path")
    )

    config = load_config(write_profile(tmp_path, profile))

    assert config.runtime_report_path == (
        state_home / "irigate/test-profile/runtime-report.json"
    )


@pytest.mark.parametrize("xdg_state_home", [None, "", "relative/state"])
def test_missing_runtime_report_path_falls_back_to_local_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    xdg_state_home: str | None,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    if xdg_state_home is None:
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_STATE_HOME", xdg_state_home)
    profile = "\n".join(
        line
        for line in VALID_PROFILE.splitlines()
        if not line.startswith("runtime_report_path")
    )

    config = load_config(write_profile(tmp_path, profile))

    assert config.runtime_report_path == (
        home / ".local/state/irigate/test-profile/runtime-report.json"
    )


def test_relative_runtime_log_path_is_anchored_to_profile_directory(
    tmp_path: Path,
) -> None:
    profile = VALID_PROFILE.replace(
        "runtime_report_path: .irigate/report.json",
        "runtime_report_path: .irigate/report.json\nruntime_log_path: runtime/logs",
    )

    config = load_config(write_profile(tmp_path, profile))

    assert config.runtime_log_path == (tmp_path / "runtime/logs").resolve()


def test_absolute_runtime_log_path_is_preserved(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace(
        "runtime_report_path: .irigate/report.json",
        "runtime_report_path: .irigate/report.json\n"
        "runtime_log_path: /var/log/irigate/test-profile",
    )

    config = load_config(write_profile(tmp_path, profile))

    assert config.runtime_log_path == Path("/var/log/irigate/test-profile")


def test_runtime_log_path_expands_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    profile = VALID_PROFILE.replace(
        "runtime_report_path: .irigate/report.json",
        "runtime_report_path: .irigate/report.json\n"
        "runtime_log_path: ~/.local/log/irigate/test-profile",
    )

    config = load_config(write_profile(tmp_path, profile))

    assert config.runtime_log_path == home / ".local/log/irigate/test-profile"


def test_missing_runtime_log_path_stays_unset(tmp_path: Path) -> None:
    config = load_config(write_profile(tmp_path, VALID_PROFILE))

    assert config.runtime_log_path is None


def test_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace("port: 8765", "port: 8765\nport: 9000")

    with pytest.raises(ConfigurationError, match=r"duplicate key 'port'"):
        load_config(write_profile(tmp_path, profile))


def test_missing_required_broker_fields_report_actionable_examples(
    tmp_path: Path,
) -> None:
    profile = write_profile(tmp_path, "host: 127.0.0.1\n")

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(profile)

    message = str(exc_info.value)
    assert "name: required profile identifier" in message
    assert "name: local" in message
    assert "upstreams: required non-empty mapping" in message
    assert "idle_timeout_seconds: 300" in message


def test_cli_logs_actionable_error_for_missing_broker_fields(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, "host: 127.0.0.1\n")

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "--config", str(profile), "--check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "configuration error:" in result.stderr
    assert "name: local" in result.stderr
    assert "upstreams:" in result.stderr


def test_cli_uses_default_config_path(tmp_path: Path) -> None:
    config_path = tmp_path / ".config" / "irigate" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(VALID_PROFILE, encoding="utf-8")
    env = {**os.environ, "HOME": str(tmp_path), "TEST_CONTEXT7_API_KEY": "synthetic"}
    env.pop("IRIGATE_CONFIG", None)

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "--check"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "profile=test-profile" in result.stdout


def test_cli_uses_config_path_from_environment(tmp_path: Path) -> None:
    config_path = write_profile(tmp_path, VALID_PROFILE)
    env = {
        **os.environ,
        "IRIGATE_CONFIG": str(config_path),
        "TEST_CONTEXT7_API_KEY": "synthetic",
    }

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "--check"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "profile=test-profile" in result.stdout


def test_cli_config_argument_overrides_environment(tmp_path: Path) -> None:
    environment_path = tmp_path / "environment.yaml"
    environment_path.write_text(
        VALID_PROFILE.replace("name: test-profile", "name: environment-profile"),
        encoding="utf-8",
    )
    argument_path = tmp_path / "argument.yaml"
    argument_path.write_text(
        VALID_PROFILE.replace("name: test-profile", "name: argument-profile"),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "IRIGATE_CONFIG": str(environment_path),
        "TEST_CONTEXT7_API_KEY": "synthetic",
    }

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "--config", str(argument_path), "--check"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "profile=argument-profile" in result.stdout


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


def test_resolves_literal_and_referenced_environment_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_CONTEXT7_API_KEY", "synthetic-secret-value")
    profile = VALID_PROFILE.replace(
        "      CONTEXT7_API_KEY: ${TEST_CONTEXT7_API_KEY}",
        "      CONTEXT7_API_KEY: ${TEST_CONTEXT7_API_KEY}\n      LOG_LEVEL: debug",
    )

    config = load_config(write_profile(tmp_path, profile))

    assert config.environment_names == frozenset({"TEST_CONTEXT7_API_KEY"})
    assert config.resolve_environment()["context7"] == {
        "CONTEXT7_API_KEY": "synthetic-secret-value",
        "LOG_LEVEL": "debug",
    }


def test_rejects_non_string_environment_values(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace("${TEST_CONTEXT7_API_KEY}", "true")

    with pytest.raises(ConfigurationError, match="environment values must be strings"):
        load_config(write_profile(tmp_path, profile))


def test_rejects_environment_references_in_arguments(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace(
        "args: [-m, echo_server]", "args: [-m, echo_server, '${TEST_CONTEXT7_API_KEY}']"
    )

    with pytest.raises(ConfigurationError, match="arguments must not contain"):
        load_config(write_profile(tmp_path, profile))


def test_loads_workspace_input_and_expands_allowed_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", "/home/synthetic-user")
    monkeypatch.setenv("PROJECT_ROOT", "/srv/synthetic-projects")
    profile = workspace_profile(
        ["/home/*/src", "/srv/**/projects", "~/src", "${PROJECT_ROOT}/*"]
    )

    config = load_config(write_profile(tmp_path, profile))

    workspace = config.upstreams["echo"].inputs["workspace"]
    assert workspace.type == "directory"
    assert workspace.required is True
    assert workspace.allowed_roots == (
        "/home/*/src",
        "/srv/**/projects",
        "/home/synthetic-user/src",
        "/srv/synthetic-projects/*",
    )


def test_loads_ordered_workspace_input_sources(tmp_path: Path) -> None:
    profile = workspace_profile(
        ["/srv/projects"],
        args="[-m, echo_server, '{filesystem.workspace|github.workspace|workspace}']",
    )

    config = load_config(write_profile(tmp_path, profile))

    assert config.upstreams["echo"].workspace_sources == (
        "filesystem.workspace",
        "github.workspace",
        "workspace",
    )


@pytest.mark.parametrize(
    ("profile", "error"),
    [
        (workspace_profile([]), "allowed_roots"),
        (workspace_profile(["/srv/projects"], input_name="repository"), "workspace"),
        (workspace_profile(["/srv/projects"], input_type="file"), "directory"),
        (workspace_profile(["/srv/projects"], required="null"), "required"),
        (workspace_profile(["/srv/projects"], args="[-m, echo_server]"), "placeholder"),
        (
            workspace_profile(
                ["/srv/projects"],
                args="[-m, echo_server, '{workspace}', '{workspace}']",
            ),
            "exactly one",
        ),
        (
            VALID_PROFILE.replace(
                "args: [-m, echo_server]", "args: [-m, echo_server, '{workspace}']"
            ),
            "without inputs",
        ),
    ],
)
def test_rejects_invalid_workspace_input_schema(
    tmp_path: Path, profile: str, error: str
) -> None:
    with pytest.raises(ConfigurationError, match=error):
        load_config(write_profile(tmp_path, profile))


@pytest.mark.parametrize(
    "pattern",
    [
        "relative/projects",
        "~other/projects",
        "/srv/~/projects",
        "/srv/proj*",
        "/srv/***",
        "/srv/[ab]/projects",
        "/srv/{one,two}",
        "/srv/../projects",
        "$PROJECT_ROOT/projects",
        "$(pwd)/projects",
    ],
)
def test_rejects_invalid_allowed_root_patterns(tmp_path: Path, pattern: str) -> None:
    with pytest.raises(ConfigurationError, match="allowed_roots"):
        load_config(write_profile(tmp_path, workspace_profile([pattern])))


def test_rejects_missing_allowed_root_environment_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MISSING_WORKSPACE_ROOT", raising=False)

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(
            write_profile(
                tmp_path, workspace_profile(["${MISSING_WORKSPACE_ROOT}/projects"])
            )
        )

    assert "MISSING_WORKSPACE_ROOT" in str(exc_info.value)


def test_rejects_wildcard_from_allowed_root_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", "/srv/*")

    with pytest.raises(ConfigurationError, match="must not contain wildcards"):
        load_config(
            write_profile(tmp_path, workspace_profile(["${WORKSPACE_ROOT}/projects"]))
        )


def test_rejects_dynamic_inputs_on_shareable_upstream(tmp_path: Path) -> None:
    profile = VALID_PROFILE.replace(
        "args: [-y, '@upstash/context7-mcp']",
        "args: [-y, '@upstash/context7-mcp', '{workspace}']",
    ).replace(
        "    shareable: true",
        "    inputs:\n"
        "      workspace:\n"
        "        type: directory\n"
        "        required: true\n"
        "        allowed_roots: ['/srv/projects']\n"
        "    shareable: true",
        1,
    )

    with pytest.raises(ConfigurationError, match="non-shareable"):
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


def test_cli_call_invokes_namespaced_tool_with_json_arguments(tmp_path: Path) -> None:
    echo_server = Path(__file__).parent / "fixtures" / "echo_server.py"
    profile = write_profile(
        tmp_path,
        "\n".join(
            [
                "name: tool-call",
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
        [
            sys.executable,
            "-m",
            "irigate",
            "call",
            "--config",
            str(profile),
            "echo__repeat",
            "--arguments",
            '{"value":"from-cli"}',
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["isError"] is False
    assert output["structuredContent"] == {"value": "from-cli"}


@pytest.mark.parametrize("arguments", ["not-json", "[]", '"value"'])
def test_cli_call_rejects_arguments_that_are_not_json_objects(
    tmp_path: Path, arguments: str
) -> None:
    profile = write_profile(tmp_path, VALID_PROFILE)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "irigate",
            "call",
            "--config",
            str(profile),
            "echo__repeat",
            "--arguments",
            arguments,
        ],
        text=True,
        capture_output=True,
        env={**os.environ, "TEST_CONTEXT7_API_KEY": "synthetic-secret-value"},
        check=False,
    )

    assert result.returncode == 2
    assert "arguments error:" in result.stderr
    assert "synthetic-secret-value" not in result.stdout + result.stderr


def test_cli_call_returns_nonzero_for_tool_error(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, VALID_PROFILE)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "irigate",
            "call",
            "--config",
            str(profile),
            "missing__tool",
        ],
        text=True,
        capture_output=True,
        env={**os.environ, "TEST_CONTEXT7_API_KEY": "synthetic-secret-value"},
        check=False,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["isError"] is True
    assert "unknown upstream prefix" in output["content"][0]["text"]
    assert "synthetic-secret-value" not in result.stdout + result.stderr


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

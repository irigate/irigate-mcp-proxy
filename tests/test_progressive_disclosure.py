from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from irigate.config import ConfigurationError, load_config


ECHO_SERVER = Path(__file__).parent / "fixtures" / "echo_server.py"


def write_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "\n".join(
            [
                "name: progressive-test",
                "host: 127.0.0.1",
                "port: 8765",
                "upstreams:",
                "  echo:",
                "    description: Echo test tools without retaining state.",
                "    transport: stdio",
                f"    command: {sys.executable}",
                f"    args: [{ECHO_SERVER}]",
                "    env:",
                "      SYNTHETIC_TOKEN: ${UNSET_PROGRESSIVE_TEST_TOKEN}",
                "    shareable: false",
                "    concurrency: serial",
                "    call_timeout_seconds: 5",
                "    idle_timeout_seconds: 60",
                "  broken:",
                "    description: Must remain dormant during selected discovery.",
                "    transport: stdio",
                "    command: irigate-command-that-must-not-start",
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


def run_irigate(*arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "irigate", *arguments],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=15,
    )


def test_upstreams_json_is_metadata_only_and_does_not_resolve_environment(
    tmp_path: Path,
) -> None:
    profile = write_profile(tmp_path)
    env = os.environ.copy()
    env.pop("UNSET_PROGRESSIVE_TEST_TOKEN", None)

    result = run_irigate("upstreams", "--config", str(profile), "--json", env=env)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "profile": "progressive-test",
        "upstreams": [
            {
                "name": "echo",
                "description": "Echo test tools without retaining state.",
            },
            {
                "name": "broken",
                "description": "Must remain dormant during selected discovery.",
            },
        ],
    }
    assert "UNSET_PROGRESSIVE_TEST_TOKEN" not in result.stdout + result.stderr


def test_upstream_description_is_trimmed_and_rejects_whitespace(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    content = profile.read_text(encoding="utf-8")
    profile.write_text(
        content.replace(
            "description: Echo test tools without retaining state.",
            "description: '  Echo test tools without retaining state.  '",
        ),
        encoding="utf-8",
    )

    assert (
        load_config(profile).upstreams["echo"].description
        == "Echo test tools without retaining state."
    )

    profile.write_text(
        content.replace(
            "description: Echo test tools without retaining state.",
            "description: '   '",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="description"):
        load_config(profile)


def test_tools_json_discloses_brief_metadata_for_one_upstream(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    env = {**os.environ, "UNSET_PROGRESSIVE_TEST_TOKEN": "synthetic"}

    result = run_irigate(
        "tools", "--config", str(profile), "--upstream", "echo", "--json", env=env
    )

    assert result.returncode == 0, result.stderr
    tools = json.loads(result.stdout)
    assert [tool["name"] for tool in tools] == ["echo__repeat", "echo__terminate"]
    assert all(set(tool) == {"name", "description"} for tool in tools)
    assert "inputSchema" not in result.stdout


def test_schema_json_discloses_only_the_exact_tool_schema(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    env = {**os.environ, "UNSET_PROGRESSIVE_TEST_TOKEN": "synthetic"}

    result = run_irigate(
        "schema", "--config", str(profile), "echo__repeat", env=env
    )

    assert result.returncode == 0, result.stderr
    schema = json.loads(result.stdout)
    assert schema["name"] == "echo__repeat"
    assert schema["inputSchema"]["type"] == "object"
    assert "value" in schema["inputSchema"]["properties"]
    assert "echo__terminate" not in result.stdout


def test_skill_path_points_to_the_packaged_progressive_skill() -> None:
    result = run_irigate("skill-path")

    assert result.returncode == 0, result.stderr
    skill_path = Path(result.stdout.strip())
    skill = skill_path / "SKILL.md"
    assert skill.is_file()
    content = skill.read_text(encoding="utf-8")
    for command in ("irigate upstreams", "irigate tools", "irigate schema", "irigate call"):
        assert command in content

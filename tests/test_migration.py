from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from irigate.migration import MigrationError, discover_configurations, migrate_configurations


def test_discovers_only_existing_common_agent_configurations(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    cursor = tmp_path / ".cursor" / "mcp.json"
    cursor.write_text('{"mcpServers": {}}', encoding="utf-8")
    (tmp_path / ".gemini").mkdir()
    gemini = tmp_path / ".gemini" / "settings.json"
    gemini.write_text('{"mcpServers": {}}', encoding="utf-8")

    discovered = discover_configurations(home=tmp_path, cwd=tmp_path / "project")

    assert [(item.agent, item.path) for item in discovered] == [
        ("Cursor", cursor),
        ("Gemini CLI", gemini),
    ]


def test_specific_json_file_migrates_only_that_file_and_updates_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "available-to-broker")
    source = tmp_path / "custom.json"
    source.write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcpServers": {
                    "GitHub Server": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_TOKEN": "literal-not-copied"},
                    },
                    "remote": {"url": "https://example.test/mcp"},
                },
            }
        ),
        encoding="utf-8",
    )
    untouched = tmp_path / ".cursor" / "mcp.json"
    untouched.parent.mkdir()
    untouched.write_text('{"mcpServers":{"other":{"command":"other"}}}', encoding="utf-8")
    profile = tmp_path / "irigate.yaml"

    result = migrate_configurations([source], profile_path=profile)

    migrated_source = json.loads(source.read_text(encoding="utf-8"))
    assert migrated_source["theme"] == "dark"
    assert migrated_source["mcpServers"]["remote"] == {"url": "https://example.test/mcp"}
    assert migrated_source["mcpServers"]["irigate"]["url"] == (
        "http://127.0.0.1:8765/mcp?upstreams=github-server&agent=generic"
    )
    assert "GitHub Server" not in migrated_source["mcpServers"]
    assert json.loads(untouched.read_text(encoding="utf-8"))["mcpServers"]["other"]
    migrated_profile = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert migrated_profile["upstreams"]["github-server"] == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        "shareable": False,
        "concurrency": "serial",
        "call_timeout_seconds": 30,
        "idle_timeout_seconds": 300,
    }
    assert source.with_name("custom.json.irigate.bak").exists()
    assert result.server_count == 1


def test_migrates_gemini_http_field_and_hermes_yaml(tmp_path: Path) -> None:
    gemini = tmp_path / ".gemini" / "settings.json"
    gemini.parent.mkdir()
    gemini.write_text(
        '{"mcpServers":{"docs":{"command":"npx","args":["docs"]}}}',
        encoding="utf-8",
    )
    hermes = tmp_path / ".hermes" / "config.yaml"
    hermes.parent.mkdir()
    hermes.write_text(
        "model: test\nmcp_servers:\n  graph:\n    command: graph\n    args: [serve]\n",
        encoding="utf-8",
    )
    profile = tmp_path / "profile.yaml"

    migrate_configurations([gemini, hermes], profile_path=profile)

    assert json.loads(gemini.read_text(encoding="utf-8"))["mcpServers"] == {
        "irigate": {
            "httpUrl": "http://127.0.0.1:8765/mcp?upstreams=docs&agent=gemini"
        }
    }
    migrated_hermes = yaml.safe_load(hermes.read_text(encoding="utf-8"))
    assert migrated_hermes["model"] == "test"
    assert migrated_hermes["mcp_servers"] == {
        "irigate": {"url": "http://127.0.0.1:8765/mcp?upstreams=graph&agent=hermes"}
    }


def test_migrates_codex_toml_without_losing_other_settings(tmp_path: Path) -> None:
    source = tmp_path / ".codex" / "config.toml"
    source.parent.mkdir()
    source.write_text(
        'model = "gpt-test"\n\n[mcp_servers.docs]\ncommand = "npx"\nargs = ["docs"]\n',
        encoding="utf-8",
    )
    profile = tmp_path / "profile.yaml"

    migrate_configurations([source], profile_path=profile)

    text = source.read_text(encoding="utf-8")
    assert 'model = "gpt-test"' in text
    assert "[mcp_servers.docs]" not in text
    assert "[mcp_servers.irigate]" in text
    assert 'url = "http://127.0.0.1:8765/mcp?upstreams=docs&agent=codex"' in text


def test_rejects_missing_broker_environment_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "mcp.json"
    original = '{"mcpServers":{"secret":{"command":"server","env":{"TOKEN":"secret"}}}}'
    source.write_text(original, encoding="utf-8")

    with pytest.raises(MigrationError, match="export TOKEN"):
        migrate_configurations([source], profile_path=tmp_path / "profile.yaml", environ={})

    assert source.read_text(encoding="utf-8") == original
    assert not source.with_name("mcp.json.irigate.bak").exists()


def test_rejects_conflicting_server_names_before_writing(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"mcpServers":{"docs":{"command":"one"}}}', encoding="utf-8")
    second.write_text('{"mcpServers":{"docs":{"command":"two"}}}', encoding="utf-8")

    with pytest.raises(MigrationError, match="conflicting MCP server key 'docs'"):
        migrate_configurations([first, second], profile_path=tmp_path / "profile.yaml")

    assert json.loads(first.read_text(encoding="utf-8"))["mcpServers"]["docs"]
    assert json.loads(second.read_text(encoding="utf-8"))["mcpServers"]["docs"]


def test_cli_specific_file_does_not_require_existing_irigate_profile(tmp_path: Path) -> None:
    source = tmp_path / "mcp.json"
    source.write_text('{"mcpServers":{"docs":{"command":"npx","args":["docs"]}}}', encoding="utf-8")
    profile = tmp_path / "profile.yaml"

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "migrate", str(source), "--config", str(profile)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"migrated {source}" in result.stdout
    assert profile.exists()


def test_cli_discovery_requires_selection_when_not_interactive(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = home / ".cursor" / "mcp.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"mcpServers":{"docs":{"command":"npx"}}}', encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "irigate", "migrate", "--config", str(tmp_path / "profile.yaml")],
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )

    assert result.returncode == 2
    assert "use --all or provide a configuration file" in result.stderr
    assert source.read_text(encoding="utf-8").startswith('{"mcpServers":{"docs"')

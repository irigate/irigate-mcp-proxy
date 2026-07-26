from __future__ import annotations

from pathlib import Path

import pytest
from mcp import types

from irigate.config import load_config
from irigate.doctor import (
    DoctorError,
    diagnose_wsl_path_arguments,
    infer_wsl_path_arguments,
    merge_wsl_path_arguments,
    repair_wsl_path_arguments,
)
from irigate.models import BrokerConfig


def tool(name: str, properties: dict[str, object]) -> types.Tool:
    return types.Tool(
        name=name,
        description=f"Synthetic {name}",
        inputSchema={"type": "object", "properties": properties},
    )


def profile_text() -> str:
    return """\
name: doctor-test
host: 127.0.0.1
port: 8765
upstreams:
  pencil:
    # Keep this operator comment.
    command: pencil.exe
    args: ["--app", "desktop"]
    execution: wsl-windows
    env: {}
    shareable: false
    concurrency: serial
    idle_timeout_seconds: 300
  native:
    command: python3
    args: [-m, fixture]
    env: {}
    shareable: false
    concurrency: serial
    idle_timeout_seconds: 300
"""


def test_infers_only_file_and_directory_paths_from_tool_schemas() -> None:
    tools = [
        tool(
            "pencil__export_html",
            {
                "filePath": {"type": "string", "description": "Open .pen document"},
                "outputPath": {"type": "string", "description": "HTML output file"},
                "prompt": {"type": "string"},
                "url": {"type": "string"},
            },
        ),
        tool(
            "pencil__export_nodes",
            {
                "filePath": {"type": "string"},
                "outputDir": {"type": "string"},
                "nested": {
                    "type": "object",
                    "properties": {
                        "requestFilePath": {"type": ["string", "null"]},
                        "jsonPath": {"type": "string"},
                    },
                },
            },
        ),
    ]

    assert infer_wsl_path_arguments("pencil", tools) == {
        "export_html": ("/filePath", "/outputPath"),
        "export_nodes": (
            "/filePath",
            "/outputDir",
            "/nested/requestFilePath",
        ),
    }


def test_merges_discovered_paths_without_replacing_operator_entries() -> None:
    configured = {
        "*": ("/filePath",),
        "custom_tool": ("/customPath",),
    }
    discovered = {
        "export_html": ("/filePath", "/outputPath"),
        "export_nodes": ("/filePath", "/outputDir"),
    }

    assert merge_wsl_path_arguments(configured, discovered) == {
        "*": ("/filePath",),
        "custom_tool": ("/customPath",),
        "export_html": ("/outputPath",),
        "export_nodes": ("/outputDir",),
    }


@pytest.mark.asyncio
async def test_diagnoses_only_wsl_windows_upstreams() -> None:
    config = BrokerConfig.model_validate(
        {
            "name": "doctor",
            "upstreams": {
                "pencil": {
                    "command": "pencil.exe",
                    "execution": "wsl-windows",
                    "wsl_path_arguments": {"*": ["/filePath"]},
                    "idle_timeout_seconds": 300,
                },
                "native": {
                    "command": "python3",
                    "idle_timeout_seconds": 300,
                },
            },
        }
    )
    discovered: list[str] = []

    async def discover(upstream: str) -> list[types.Tool]:
        discovered.append(upstream)
        return [
            tool(
                f"{upstream}__export_html",
                {
                    "filePath": {"type": "string"},
                    "outputPath": {"type": "string"},
                },
            )
        ]

    findings = await diagnose_wsl_path_arguments(config, discover)

    assert discovered == ["pencil"]
    assert len(findings) == 1
    assert findings[0].needs_repair is True
    assert findings[0].recommended == {
        "*": ("/filePath",),
        "export_html": ("/outputPath",),
    }


def test_repair_adds_mapping_atomically_and_preserves_other_profile_text(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile.yaml"
    original = profile_text()
    profile.write_text(original, encoding="utf-8")

    backup = repair_wsl_path_arguments(
        profile,
        {
            "pencil": {
                "export_html": ("/filePath", "/outputPath"),
                "export_nodes": ("/filePath", "/outputDir"),
            }
        },
    )

    updated = profile.read_text(encoding="utf-8")
    assert "# Keep this operator comment." in updated
    assert "  native:\n" in updated
    assert "    wsl_path_arguments:\n" in updated
    assert '      "export_html": ["/filePath", "/outputPath"]\n' in updated
    assert backup == profile.with_name("profile.yaml.irigate-doctor.bak")
    assert backup.read_text(encoding="utf-8") == original
    assert load_config(profile).upstreams["pencil"].wsl_path_arguments == {
        "export_html": ("/filePath", "/outputPath"),
        "export_nodes": ("/filePath", "/outputDir"),
    }
    assert not profile.with_name("profile.yaml.irigate-doctor.tmp").exists()


def test_repair_updates_existing_mapping_without_overwriting_first_backup(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile.yaml"
    profile.write_text(profile_text(), encoding="utf-8")
    repair_wsl_path_arguments(
        profile, {"pencil": {"export_html": ("/filePath",)}}
    )
    backup = profile.with_name("profile.yaml.irigate-doctor.bak")
    original_backup = backup.read_text(encoding="utf-8")

    created = repair_wsl_path_arguments(
        profile,
        {"pencil": {"export_nodes": ("/filePath", "/outputDir")}},
    )

    assert created is None
    assert backup.read_text(encoding="utf-8") == original_backup
    configured = load_config(profile).upstreams["pencil"].wsl_path_arguments
    assert configured == {"export_nodes": ("/filePath", "/outputDir")}


def test_repair_rejects_unknown_upstream_without_writing(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    original = profile_text()
    profile.write_text(original, encoding="utf-8")

    with pytest.raises(DoctorError, match="unknown upstream"):
        repair_wsl_path_arguments(
            profile, {"missing": {"tool": ("/filePath",)}}
        )

    assert profile.read_text(encoding="utf-8") == original

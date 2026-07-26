from __future__ import annotations

import os
import json
import shutil
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from mcp import types
from yaml.nodes import MappingNode, Node, ScalarNode

from irigate.config import ConfigurationError, load_config
from irigate.models import BrokerConfig


class DoctorError(ValueError):
    """A safe-to-display profile diagnosis or repair failure."""


@dataclass(frozen=True)
class WslPathFinding:
    upstream: str
    discovered: dict[str, tuple[str, ...]]
    configured: dict[str, tuple[str, ...]]
    recommended: dict[str, tuple[str, ...]]

    @property
    def needs_repair(self) -> bool:
        return self.recommended != self.configured


_PATH_FIELD_SUFFIXES = (
    "filepath",
    "directorypath",
    "dirpath",
    "outputpath",
    "outputdir",
)
_PATH_FIELD_EXCLUSIONS = frozenset({"jsonpath", "xpath", "urlpath"})


def _is_string_schema(schema: object) -> bool:
    if not isinstance(schema, Mapping):
        return False
    value_type = schema.get("type")
    if value_type == "string":
        return True
    if isinstance(value_type, Sequence) and not isinstance(value_type, (str, bytes)):
        return "string" in value_type
    variants = schema.get("anyOf") or schema.get("oneOf")
    return isinstance(variants, Sequence) and any(_is_string_schema(item) for item in variants)


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _is_path_field(name: str) -> bool:
    lowered = name.lower()
    return lowered not in _PATH_FIELD_EXCLUSIONS and lowered.endswith(
        _PATH_FIELD_SUFFIXES
    )


def _schema_path_pointers(schema: object, prefix: str = "") -> tuple[str, ...]:
    if not isinstance(schema, Mapping):
        return ()
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    pointers: list[str] = []
    for raw_name, child in properties.items():
        name = str(raw_name)
        pointer = prefix + "/" + _escape_pointer_token(name)
        if _is_path_field(name) and _is_string_schema(child):
            pointers.append(pointer)
        if isinstance(child, Mapping) and child.get("type") == "object":
            pointers.extend(_schema_path_pointers(child, pointer))
    return tuple(pointers)


def infer_wsl_path_arguments(
    upstream_key: str, tools: Sequence[types.Tool]
) -> dict[str, tuple[str, ...]]:
    """Infer explicit WSL path pointers from one upstream's advertised schemas."""

    prefix = upstream_key + "__"
    inferred: dict[str, tuple[str, ...]] = {}
    for tool in tools:
        if not tool.name.startswith(prefix):
            continue
        pointers = _schema_path_pointers(tool.inputSchema)
        if pointers:
            inferred[tool.name.removeprefix(prefix)] = pointers
    return inferred


def merge_wsl_path_arguments(
    configured: Mapping[str, Sequence[str]],
    discovered: Mapping[str, Sequence[str]],
) -> dict[str, tuple[str, ...]]:
    """Merge inferred pointers without changing operator-authored mappings."""

    merged = {name: tuple(pointers) for name, pointers in configured.items()}
    global_pointers = frozenset(merged.get("*", ()))
    for tool, pointers in discovered.items():
        existing = merged.get(tool, ())
        additions = tuple(
            pointer
            for pointer in pointers
            if pointer not in global_pointers and pointer not in existing
        )
        if additions:
            merged[tool] = existing + additions
    return merged


async def diagnose_wsl_path_arguments(
    config: BrokerConfig,
    discover: Callable[[str], Awaitable[Sequence[types.Tool]]],
) -> tuple[WslPathFinding, ...]:
    """Inspect every WSL-to-Windows upstream and recommend schema-derived mappings."""

    findings: list[WslPathFinding] = []
    for upstream, definition in config.upstreams.items():
        if definition.execution != "wsl-windows":
            continue
        tools = await discover(upstream)
        discovered = infer_wsl_path_arguments(upstream, tools)
        configured = dict(definition.wsl_path_arguments)
        findings.append(
            WslPathFinding(
                upstream=upstream,
                discovered=discovered,
                configured=configured,
                recommended=merge_wsl_path_arguments(configured, discovered),
            )
        )
    return tuple(findings)


def _mapping_value(node: MappingNode, name: str) -> Node | None:
    for key, value in node.value:
        if isinstance(key, ScalarNode) and key.value == name:
            return value
    return None


def _mapping_pair(node: MappingNode, name: str) -> tuple[Node, Node] | None:
    for key, value in node.value:
        if isinstance(key, ScalarNode) and key.value == name:
            return key, value
    return None


def _line_start(text: str, index: int) -> int:
    newline = text.rfind("\n", 0, index)
    return 0 if newline < 0 else newline + 1


def _line_end(text: str, index: int) -> int:
    newline = text.find("\n", index)
    return len(text) if newline < 0 else newline + 1


def _render_mapping(indent: int, mappings: Mapping[str, Sequence[str]]) -> str:
    prefix = " " * indent
    lines = [f"{prefix}wsl_path_arguments:\n"]
    for tool, pointers in mappings.items():
        rendered = ", ".join(json.dumps(pointer) for pointer in pointers)
        tool_name = json.dumps(tool)
        lines.append(f"{prefix}  {tool_name}: [{rendered}]\n")
    return "".join(lines)


def _profile_replacements(
    text: str, repairs: Mapping[str, Mapping[str, Sequence[str]]]
) -> list[tuple[int, int, str]]:
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise DoctorError("cannot parse Irigate profile for repair") from exc
    if not isinstance(root, MappingNode):
        raise DoctorError("Irigate profile root must be a block mapping")
    upstreams = _mapping_value(root, "upstreams")
    if not isinstance(upstreams, MappingNode):
        raise DoctorError("Irigate profile upstreams must be a block mapping")

    upstream_nodes = {
        str(key.value): value
        for key, value in upstreams.value
        if isinstance(key, ScalarNode) and isinstance(value, MappingNode)
    }
    replacements: list[tuple[int, int, str]] = []
    for upstream, mappings in repairs.items():
        node = upstream_nodes.get(upstream)
        if node is None:
            raise DoctorError(f"unknown upstream in repair: {upstream}")
        if not mappings:
            continue
        rendered = _render_mapping(node.start_mark.column, mappings)
        existing = _mapping_pair(node, "wsl_path_arguments")
        if existing is not None:
            key, value = existing
            start = _line_start(text, key.start_mark.index)
            end = _line_end(text, value.end_mark.index)
            replacements.append((start, end, rendered))
            continue
        execution = _mapping_pair(node, "execution")
        if execution is None:
            raise DoctorError(
                f"upstream '{upstream}' has no explicit execution field"
            )
        _, execution_value = execution
        insertion = _line_end(text, execution_value.end_mark.index)
        replacements.append((insertion, insertion, rendered))
    return replacements


def repair_wsl_path_arguments(
    profile_path: Path | str,
    repairs: Mapping[str, Mapping[str, Sequence[str]]],
) -> Path | None:
    """Atomically write diagnosed mappings, preserving profile text and one backup."""

    path = Path(profile_path).expanduser()
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DoctorError(f"cannot read Irigate profile: {path}") from exc
    replacements = _profile_replacements(original, repairs)
    if not replacements:
        return None
    updated = original
    for start, end, rendered in sorted(replacements, reverse=True):
        updated = updated[:start] + rendered + updated[end:]
    if updated == original:
        return None

    temporary = path.with_name(path.name + ".irigate-doctor.tmp")
    backup = path.with_name(path.name + ".irigate-doctor.bak")
    created_backup = False
    try:
        temporary.write_text(updated, encoding="utf-8")
        load_config(temporary)
        if not backup.exists():
            shutil.copy2(path, backup)
            created_backup = True
        os.replace(temporary, path)
    except ConfigurationError as exc:
        temporary.unlink(missing_ok=True)
        raise DoctorError(f"repaired profile is invalid: {exc}") from exc
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DoctorError(f"cannot write repaired Irigate profile: {path}") from exc
    return backup if created_backup else None

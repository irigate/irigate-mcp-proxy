from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
import yaml
from pydantic import ValidationError
from tomlkit.exceptions import ParseError

from irigate.models import BrokerConfig


class MigrationError(ValueError):
    """A safe-to-display migration failure."""


@dataclass(frozen=True)
class ConfigurationCandidate:
    agent: str
    path: Path


@dataclass(frozen=True)
class MigrationResult:
    paths: tuple[Path, ...]
    server_count: int
    profile_path: Path


@dataclass
class _Document:
    candidate: ConfigurationCandidate
    value: MutableMapping[str, Any]
    containers: list[MutableMapping[str, Any]]
    format: str


_DISCOVERY_PATHS = (
    ("Claude Code", ".claude.json"),
    ("Cursor", ".cursor/mcp.json"),
    ("Gemini CLI", ".gemini/settings.json"),
    ("Codex CLI", ".codex/config.toml"),
    ("Hermes", ".hermes/config.yaml"),
)
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
_ENV_REFERENCE = re.compile(r"^(?:\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?|%([A-Za-z_][A-Za-z0-9_]*)%)$")


def discover_configurations(
    *, home: Path | None = None, cwd: Path | None = None
) -> list[ConfigurationCandidate]:
    home = Path.home() if home is None else home
    cwd = Path.cwd() if cwd is None else cwd
    candidates = [
        ConfigurationCandidate(agent, home / relative)
        for agent, relative in _DISCOVERY_PATHS
        if (home / relative).is_file()
    ]
    project_paths = (
        ("Claude Code", cwd / ".mcp.json"),
        ("Cursor", cwd / ".cursor" / "mcp.json"),
        ("Gemini CLI", cwd / ".gemini" / "settings.json"),
        ("Codex CLI", cwd / ".codex" / "config.toml"),
    )
    seen = {candidate.path.resolve() for candidate in candidates}
    for agent, path in project_paths:
        if path.is_file() and path.resolve() not in seen:
            candidates.append(ConfigurationCandidate(agent, path))
            seen.add(path.resolve())
    return candidates


def _infer_candidate(path: Path) -> ConfigurationCandidate:
    normalized = path.as_posix().lower()
    if path.name == ".claude.json" or path.name == ".mcp.json":
        agent = "Claude Code"
    elif "/.cursor/" in normalized:
        agent = "Cursor"
    elif "/.gemini/" in normalized:
        agent = "Gemini CLI"
    elif path.suffix == ".toml" or "/.codex/" in normalized:
        agent = "Codex CLI"
    elif "/.hermes/" in normalized:
        agent = "Hermes"
    else:
        agent = "Generic"
    return ConfigurationCandidate(agent, path)


def _mapping(value: object, description: str) -> MutableMapping[str, Any]:
    if not isinstance(value, MutableMapping):
        raise MigrationError(f"{description} must be a mapping")
    return value


def _load_document(candidate: ConfigurationCandidate) -> _Document:
    path = candidate.path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MigrationError(f"cannot read agent configuration: {path}") from exc
    try:
        if path.suffix == ".toml":
            value = _mapping(tomlkit.parse(text), f"configuration root in {path}")
            container = value.get("mcp_servers", {})
            return _Document(candidate, value, [_mapping(container, "mcp_servers")], "toml")
        if path.suffix in {".yaml", ".yml"}:
            value = _mapping(yaml.safe_load(text), f"configuration root in {path}")
            container = value.get("mcp_servers", {})
            return _Document(candidate, value, [_mapping(container, "mcp_servers")], "yaml")
        value = _mapping(json.loads(text), f"configuration root in {path}")
    except (json.JSONDecodeError, ParseError, yaml.YAMLError) as exc:
        raise MigrationError(f"invalid {path.suffix.lstrip('.').upper()} configuration: {path}") from exc

    containers: list[MutableMapping[str, Any]] = []
    if "mcpServers" in value:
        containers.append(_mapping(value["mcpServers"], "mcpServers"))
    projects = value.get("projects")
    if isinstance(projects, Mapping):
        for project in projects.values():
            if isinstance(project, MutableMapping) and "mcpServers" in project:
                containers.append(_mapping(project["mcpServers"], "projects.*.mcpServers"))
    if not containers:
        raise MigrationError(f"no MCP server mapping found in {path}")
    return _Document(candidate, value, containers, "json")


def _upstream_key(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not key or not key[0].isalpha() or _KEY_PATTERN.fullmatch(key) is None:
        raise MigrationError(f"MCP server name cannot become an Irigate key: {name!r}")
    return key


def _environment_reference(
    child_name: str, raw_value: object, environ: Mapping[str, str]
) -> str:
    if not isinstance(raw_value, str):
        raise MigrationError(f"environment value for {child_name} must be a string")
    match = _ENV_REFERENCE.fullmatch(raw_value)
    reference = next((part for part in match.groups() if part), child_name) if match else child_name
    if reference not in environ:
        raise MigrationError(
            f"export {reference} in the Irigate broker environment before migrating {child_name}"
        )
    return "${" + reference + "}"


def _convert_server(
    name: str, raw: object, environ: Mapping[str, str], base_directory: Path
) -> tuple[str, dict[str, object]] | None:
    server = _mapping(raw, f"MCP server {name!r}")
    command = server.get("command")
    if command is None:
        return None
    if not isinstance(command, str) or not command or any(char.isspace() for char in command):
        raise MigrationError(f"MCP server {name!r} has an invalid command")
    args = server.get("args", [])
    if not isinstance(args, Sequence) or isinstance(args, (str, bytes)) or not all(
        isinstance(item, str) for item in args
    ):
        raise MigrationError(f"MCP server {name!r} args must be a string array")
    raw_env = server.get("env", {})
    if not isinstance(raw_env, Mapping):
        raise MigrationError(f"MCP server {name!r} env must be a mapping")
    env = {
        str(child_name): _environment_reference(str(child_name), value, environ)
        for child_name, value in raw_env.items()
    }
    upstream: dict[str, object] = {
        "transport": "stdio",
        "command": str(command),
        "args": [str(item) for item in args],
        "env": env,
        "shareable": False,
        "concurrency": "serial",
        "call_timeout_seconds": 30,
        "idle_timeout_seconds": 300,
    }
    cwd = server.get("cwd")
    if cwd is not None:
        if not isinstance(cwd, str) or not cwd:
            raise MigrationError(f"MCP server {name!r} cwd must be a non-empty string")
        cwd_path = Path(str(cwd)).expanduser()
        upstream["cwd"] = str(cwd_path if cwd_path.is_absolute() else base_directory / cwd_path)
    return _upstream_key(name), upstream


def _configuration_base(candidate: ConfigurationCandidate) -> Path:
    if candidate.path.parent.name in {".cursor", ".gemini", ".codex", ".hermes"}:
        return candidate.path.parent.parent
    return candidate.path.parent


def _agent_label(agent: str) -> str:
    return {
        "Claude Code": "claude-code",
        "Cursor": "cursor",
        "Gemini CLI": "gemini",
        "Codex CLI": "codex",
        "Hermes": "hermes",
        "Generic": "generic",
    }[agent]


def _irigate_entry(agent: str, url: str) -> MutableMapping[str, Any]:
    if agent == "Gemini CLI":
        return {"httpUrl": url}
    if agent == "Claude Code":
        return {"type": "http", "url": url}
    return {"url": url}


def _render(document: _Document) -> str:
    if document.format == "toml":
        return tomlkit.dumps(document.value)
    if document.format == "yaml":
        return yaml.safe_dump(document.value, sort_keys=False)
    return json.dumps(document.value, indent=2) + "\n"


def _load_profile(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "name": "migrated",
            "host": "127.0.0.1",
            "port": 8765,
            "upstreams": {},
        }
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MigrationError(f"cannot read Irigate profile: {path}") from exc
    if not isinstance(raw, dict):
        raise MigrationError(f"Irigate profile root must be a mapping: {path}")
    return raw


def migrate_configurations(
    paths: Sequence[Path | str],
    *,
    profile_path: Path | str,
    environ: Mapping[str, str] | None = None,
) -> MigrationResult:
    if not paths:
        raise MigrationError("no agent configurations selected")
    environment = os.environ if environ is None else environ
    profile_path = Path(profile_path).expanduser()
    profile = _load_profile(profile_path)
    profile_upstreams = _mapping(profile.setdefault("upstreams", {}), "Irigate upstreams")
    host = profile.get("host", "127.0.0.1")
    port = profile.get("port", 8765)
    endpoint_host = f"[{host}]" if isinstance(host, str) and ":" in host else host
    endpoint = f"http://{endpoint_host}:{port}/mcp"
    documents = [_load_document(_infer_candidate(Path(path).expanduser())) for path in paths]
    converted: dict[str, dict[str, object]] = {}

    for document in documents:
        for container in document.containers:
            selected_keys: list[str] = []
            migrated_names: list[str] = []
            for name, raw_server in list(container.items()):
                if name == "irigate":
                    continue
                converted_server = _convert_server(
                    str(name), raw_server, environment, _configuration_base(document.candidate)
                )
                if converted_server is None:
                    continue
                key, upstream = converted_server
                existing = converted.get(key) or profile_upstreams.get(key)
                if existing is not None and dict(existing) != upstream:
                    raise MigrationError(f"conflicting MCP server key '{key}'")
                converted[key] = upstream
                selected_keys.append(key)
                migrated_names.append(str(name))
            if not selected_keys:
                continue
            for name in migrated_names:
                del container[name]
            url = (
                endpoint
                + "?upstreams="
                + ",".join(dict.fromkeys(selected_keys))
                + "&agent="
                + _agent_label(document.candidate.agent)
            )
            if document.format == "toml":
                entry = tomlkit.table()
                entry.add("url", url)
                container["irigate"] = entry
            else:
                container["irigate"] = _irigate_entry(document.candidate.agent, url)

    if not converted:
        raise MigrationError("selected configurations contain no stdio MCP servers")
    profile_upstreams.update(converted)
    try:
        BrokerConfig.model_validate(profile)
    except ValidationError as exc:
        raise MigrationError(f"migrated Irigate profile is invalid: {exc.errors(include_input=False)}") from exc

    rendered = {document.candidate.path: _render(document) for document in documents}
    rendered[profile_path] = yaml.safe_dump(profile, sort_keys=False)
    backups: list[tuple[Path, Path]] = []
    originals: dict[Path, str | None] = {}
    try:
        for path in rendered:
            originals[path] = path.read_text(encoding="utf-8") if path.exists() else None
            if path.exists():
                backup = path.with_name(path.name + ".irigate.bak")
                if backup.exists():
                    raise MigrationError(f"backup already exists: {backup}")
                shutil.copy2(path, backup)
                backups.append((path, backup))
        for path, text in rendered.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".irigate.tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
    except Exception:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(original, encoding="utf-8")
        for _, backup in backups:
            backup.unlink(missing_ok=True)
        raise

    return MigrationResult(
        paths=tuple(document.candidate.path for document in documents),
        server_count=len(converted),
        profile_path=profile_path,
    )

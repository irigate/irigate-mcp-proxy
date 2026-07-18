from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode

from irigate.models import BrokerConfig


class ConfigurationError(ValueError):
    """A safe-to-display profile validation error."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConfigurationError(
                f"duplicate key '{key}' at line {key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _format_validation_error(error: ValidationError) -> str:
    messages: list[str] = []
    for item in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        if item["type"] == "missing" and item["loc"] == ("name",):
            messages.append(
                "name: required profile identifier (example: name: local)"
            )
            continue
        if item["type"] == "missing" and item["loc"] == ("upstreams",):
            messages.append(
                "upstreams: required non-empty mapping "
                "(example: upstreams: {echo: {command: python3, "
                "args: [-m, echo_server], idle_timeout_seconds: 300}})"
            )
            continue
        message = str(item["msg"]).removeprefix("Value error, ")
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages)


def load_config(path: str | Path) -> BrokerConfig:
    """Load one YAML profile without starting upstream processes."""

    profile_path = Path(path)
    try:
        text = profile_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"cannot read configuration: {profile_path}") from exc

    try:
        raw = yaml.load(text, Loader=_UniqueKeyLoader)
    except ConfigurationError:
        raise
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}" if mark is not None else ""
        raise ConfigurationError(f"invalid YAML{location}") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError("configuration root must be a mapping")

    try:
        config = BrokerConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from exc

    if config.runtime_report_path is not None and not config.runtime_report_path.is_absolute():
        config = config.model_copy(
            update={"runtime_report_path": (profile_path.parent / config.runtime_report_path).resolve()}
        )
    if config.runtime_log_path is not None:
        runtime_log_path = config.runtime_log_path.expanduser()
        if not runtime_log_path.is_absolute():
            runtime_log_path = profile_path.parent / runtime_log_path
        config = config.model_copy(update={"runtime_log_path": runtime_log_path.resolve()})
    return config

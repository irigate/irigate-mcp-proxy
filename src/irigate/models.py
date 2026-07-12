from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ENV_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_ENV_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_UPSTREAM_KEY = re.compile(r"^[a-z][a-z0-9-]*$")
_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_WORKSPACE_SOURCE = re.compile(r"^(?:[a-z][a-z0-9-]*\.)?workspace$")
_INPUT_PLACEHOLDER = re.compile(r"^\{([^{}]+)\}$")
QUALIFIER_UPSTREAM_KEYS = {"context7-readonly-v3": "context7"}
REGISTERED_QUALIFIERS = frozenset(QUALIFIER_UPSTREAM_KEYS)


class EnvironmentReference(BaseModel):
    """A broker-process environment variable referenced by name."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str


class WorkspaceInputConfig(BaseModel):
    """A client-supplied directory constrained by configured path patterns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["directory"]
    required: Annotated[bool, Field(strict=True)]
    allowed_roots: Annotated[tuple[str, ...], Field(min_length=1)]

    @field_validator("allowed_roots", mode="before")
    @classmethod
    def expand_and_validate_allowed_roots(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        return tuple(_expand_allowed_root(pattern) for pattern in value)


class UpstreamConfig(BaseModel):
    """Static configuration for one stdio MCP upstream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transport: Literal["stdio"] = "stdio"
    command: str
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    env: dict[str, EnvironmentReference] = Field(default_factory=dict)
    inputs: dict[str, WorkspaceInputConfig] = Field(default_factory=dict)
    shareable: bool = False
    qualifier: str | None = None
    concurrency: Literal["serial", "parallel"] = "serial"
    call_timeout_seconds: Annotated[float, Field(gt=0, le=3600)] = 30
    idle_timeout_seconds: Annotated[float, Field(gt=0, le=86400)]
    failure_threshold: Annotated[int, Field(ge=1, le=100)] = 5
    crash_threshold: Annotated[int, Field(ge=1, le=100)] = 2

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: str) -> str:
        if not value.strip() or any(character.isspace() for character in value):
            raise ValueError("command must be one non-empty executable token; use args for arguments")
        return value

    @field_validator("args")
    @classmethod
    def reject_environment_references_in_args(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(_ENV_REFERENCE.fullmatch(value) for value in values):
            raise ValueError("arguments must not contain environment references; use env")
        return values

    @field_validator("env", mode="before")
    @classmethod
    def parse_environment_references(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("env must map child variable names to ${ENV_NAME} references")
        parsed: dict[str, dict[str, str]] = {}
        for child_name, reference in value.items():
            if not isinstance(child_name, str) or not child_name:
                raise ValueError("env names must be non-empty strings")
            if not isinstance(reference, str):
                raise ValueError("environment reference must use ${ENV_NAME}")
            match = _ENV_REFERENCE.fullmatch(reference)
            if match is None:
                raise ValueError("environment reference must use ${ENV_NAME}")
            parsed[child_name] = {"name": match.group(1)}
        return parsed

    @field_validator("inputs")
    @classmethod
    def validate_inputs(
        cls, value: dict[str, WorkspaceInputConfig]
    ) -> dict[str, WorkspaceInputConfig]:
        if any(name != "workspace" for name in value):
            raise ValueError("inputs supports only the reserved workspace input")
        return value

    @model_validator(mode="after")
    def validate_shareability(self) -> UpstreamConfig:
        placeholders = tuple(
            match.group(1)
            for arg in self.args
            if (match := _INPUT_PLACEHOLDER.fullmatch(arg)) is not None
        )
        malformed_placeholders = tuple(
            arg
            for arg in self.args
            if ("{" in arg or "}" in arg) and not _INPUT_PLACEHOLDER.fullmatch(arg)
        )
        if self.inputs:
            if malformed_placeholders or len(placeholders) != 1:
                raise ValueError(
                    "workspace input requires exactly one standalone input placeholder"
                )
            sources = placeholders[0].split("|")
            if any(_WORKSPACE_SOURCE.fullmatch(source) is None for source in sources):
                raise ValueError(
                    "workspace placeholder sources must be workspace or <upstream>.workspace"
                )
            if len(sources) != len(set(sources)):
                raise ValueError("workspace placeholder sources must be unique")
            if self.shareable:
                raise ValueError("dynamic inputs require a non-shareable upstream")
        elif placeholders or malformed_placeholders:
            raise ValueError("input placeholder is invalid without inputs")
        if self.shareable and self.qualifier not in REGISTERED_QUALIFIERS:
            names = ", ".join(sorted(REGISTERED_QUALIFIERS))
            raise ValueError(f"shareable upstream requires a registered qualifier: {names}")
        if not self.shareable and self.qualifier is not None:
            raise ValueError("qualifier is only valid when shareable is true")
        return self

    @property
    def workspace_sources(self) -> tuple[str, ...]:
        if not self.inputs:
            return ()
        placeholder = next(
            match.group(1)
            for arg in self.args
            if (match := _INPUT_PLACEHOLDER.fullmatch(arg)) is not None
        )
        return tuple(placeholder.split("|"))


def _expand_allowed_root(pattern: object) -> str:
    if not isinstance(pattern, str):
        raise ValueError("allowed_roots entries must be strings")
    if pattern == "~":
        expanded = str(Path.home())
    elif pattern.startswith("~/"):
        expanded = str(Path.home()) + pattern[1:]
    else:
        expanded = pattern
    if "~" in expanded:
        raise ValueError("allowed_roots supports only a leading ~ or ~/")

    def replace_environment(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ValueError(f"allowed_roots references missing environment name {name}")
        replacement = os.environ[name]
        if not replacement.startswith("/"):
            raise ValueError(
                f"allowed_roots environment name {name} must resolve to an absolute path"
            )
        if "*" in replacement:
            raise ValueError(
                f"allowed_roots environment name {name} must not contain wildcards"
            )
        return replacement

    expanded = _ENV_INTERPOLATION.sub(replace_environment, expanded)
    if "$" in expanded:
        raise ValueError("allowed_roots environment references must use ${ENV_NAME}")
    if not expanded.startswith("/"):
        raise ValueError("allowed_roots entries must be absolute path patterns")

    segments = expanded.split("/")[1:]
    if any(not segment for segment in segments):
        raise ValueError("allowed_roots entries must not contain empty path segments")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("allowed_roots entries must not contain traversal segments")
    for segment in segments:
        if segment in {"*", "**"}:
            continue
        if any(character in segment for character in "*?[]{}"):
            raise ValueError(
                "allowed_roots wildcards must be complete * or ** path segments"
            )
    return expanded


class BrokerConfig(BaseModel):
    """Validated static broker profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    host: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535)] = 8765
    runtime_report_path: Path | None = None
    upstreams: dict[str, UpstreamConfig]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _PROFILE_NAME.fullmatch(value) is None:
            raise ValueError("profile name must use lowercase letters, digits, and hyphens")
        return value

    @field_validator("host")
    @classmethod
    def validate_loopback_host(cls, value: str) -> str:
        if value == "localhost":
            return value
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("host must be a loopback address or localhost") from exc
        if not address.is_loopback:
            raise ValueError("host must be loopback-only")
        return value

    @field_validator("upstreams")
    @classmethod
    def validate_upstream_keys(cls, value: dict[str, UpstreamConfig]) -> dict[str, UpstreamConfig]:
        if not value:
            raise ValueError("at least one upstream is required")
        invalid = sorted(key for key in value if _UPSTREAM_KEY.fullmatch(key) is None)
        if invalid:
            raise ValueError(
                "upstream keys must use lowercase letters, digits, and hyphens: "
                + ", ".join(invalid)
            )
        return value

    @model_validator(mode="after")
    def validate_qualifier_upstream_keys(self) -> BrokerConfig:
        for key, upstream in self.upstreams.items():
            expected = QUALIFIER_UPSTREAM_KEYS.get(upstream.qualifier or "")
            if upstream.shareable and expected != key:
                raise ValueError(
                    f"qualifier '{upstream.qualifier}' supports upstream key '{expected}'"
                )
        return self

    @property
    def environment_names(self) -> frozenset[str]:
        return frozenset(
            reference.name
            for upstream in self.upstreams.values()
            for reference in upstream.env.values()
        )

    def resolve_environment(
        self, environ: Mapping[str, str] | None = None
    ) -> dict[str, dict[str, str]]:
        source = os.environ if environ is None else environ
        missing = sorted(name for name in self.environment_names if name not in source)
        if missing:
            from irigate.config import ConfigurationError

            raise ConfigurationError("missing environment references: " + ", ".join(missing))
        return {
            upstream_key: {
                child_name: source[reference.name]
                for child_name, reference in upstream.env.items()
            }
            for upstream_key, upstream in self.upstreams.items()
        }

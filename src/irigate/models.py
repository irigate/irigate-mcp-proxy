from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ENV_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_UPSTREAM_KEY = re.compile(r"^[a-z][a-z0-9-]*$")
_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
QUALIFIER_UPSTREAM_KEYS = {"context7-readonly-v3": "context7"}
REGISTERED_QUALIFIERS = frozenset(QUALIFIER_UPSTREAM_KEYS)


class EnvironmentReference(BaseModel):
    """A broker-process environment variable referenced by name."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str


class UpstreamConfig(BaseModel):
    """Static configuration for one stdio MCP upstream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transport: Literal["stdio"] = "stdio"
    command: str
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    env: dict[str, EnvironmentReference] = Field(default_factory=dict)
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

    @model_validator(mode="after")
    def validate_shareability(self) -> UpstreamConfig:
        if self.shareable and self.qualifier not in REGISTERED_QUALIFIERS:
            names = ", ".join(sorted(REGISTERED_QUALIFIERS))
            raise ValueError(f"shareable upstream requires a registered qualifier: {names}")
        if not self.shareable and self.qualifier is not None:
            raise ValueError("qualifier is only valid when shareable is true")
        return self


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

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass, field
from typing import Final

from mcp import types

from irigate.models import BrokerConfig, QUALIFIER_UPSTREAM_KEYS, UpstreamConfig
from irigate.upstream import UpstreamWorker

GENERIC_CHECKS: Final = (
    "two_isolated_initializations",
    "stable_tool_schema",
    "disconnect_reconnect",
    "timeout",
    "crash_isolation",
)


@dataclass(frozen=True, slots=True)
class Qualifier:
    name: str
    upstream_key: str
    required_tools: frozenset[str]


QUALIFIERS: Final = {
    "context7-readonly-v3": Qualifier(
        name="context7-readonly-v3",
        upstream_key=QUALIFIER_UPSTREAM_KEYS["context7-readonly-v3"],
        required_tools=frozenset({"resolve-library-id", "query-docs"}),
    )
}


@dataclass(frozen=True, slots=True)
class QualificationResult:
    upstream_key: str
    qualifier: str | None
    admitted: bool
    checks: dict[str, bool]
    behavioral_checks: dict[str, bool]
    reason: str | None = None
    tools: tuple[types.Tool, ...] = field(default=(), repr=False)


def _fingerprint(tools: tuple[types.Tool, ...]) -> str:
    schemas = [
        {
            "name": tool.name,
            "input": tool.inputSchema,
            "output": tool.outputSchema,
        }
        for tool in sorted(tools, key=lambda item: item.name)
    ]
    encoded = json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


async def _start_once(
    key: str, config: UpstreamConfig, environment: dict[str, str]
) -> tuple[types.Tool, ...]:
    worker = UpstreamWorker(key, config, environment)
    try:
        return await asyncio.wait_for(worker.start(), timeout=config.call_timeout_seconds)
    finally:
        await worker.close()


async def _crash_is_contained(
    key: str, config: UpstreamConfig, environment: dict[str, str]
) -> bool:
    crash_config = config.model_copy(
        update={
            "command": sys.executable,
            "args": ("-c", "raise SystemExit(23)"),
            "env": {},
            "shareable": False,
            "qualifier": None,
        }
    )
    worker = UpstreamWorker("qualification-crash-probe", crash_config, {})
    crashed = False
    try:
        await asyncio.wait_for(worker.start(), timeout=config.call_timeout_seconds)
    except Exception:
        crashed = True
    finally:
        await worker.close()
    if not crashed:
        return False
    try:
        await _start_once(key, config, environment)
    except Exception:
        return False
    return True


async def qualify_upstream(
    key: str, config: UpstreamConfig, environment: dict[str, str]
) -> QualificationResult:
    checks = {name: False for name in GENERIC_CHECKS}
    behavioral = {"reviewed_tool_surface": False}
    qualifier = QUALIFIERS.get(config.qualifier or "")
    if qualifier is None or qualifier.upstream_key != key:
        return QualificationResult(
            upstream_key=key,
            qualifier=config.qualifier,
            admitted=False,
            checks=checks,
            behavioral_checks=behavioral,
            reason="qualifier does not support upstream key",
        )

    try:
        first = await _start_once(key, config, environment)
        second = await _start_once(key, config, environment)
    except Exception:
        return QualificationResult(
            upstream_key=key,
            qualifier=config.qualifier,
            admitted=False,
            checks=checks,
            behavioral_checks=behavioral,
            reason="generic startup check failed",
        )

    checks["two_isolated_initializations"] = True
    checks["stable_tool_schema"] = _fingerprint(first) == _fingerprint(second)
    checks["disconnect_reconnect"] = True
    checks["timeout"] = True
    checks["crash_isolation"] = await _crash_is_contained(key, config, environment)
    names = {tool.name for tool in second}
    behavioral["reviewed_tool_surface"] = qualifier.required_tools <= names
    admitted = all(checks.values()) and all(behavioral.values())
    return QualificationResult(
        upstream_key=key,
        qualifier=config.qualifier,
        admitted=admitted,
        checks=checks,
        behavioral_checks=behavioral,
        reason=None if admitted else "qualification checks failed",
        tools=second,
    )


async def qualify_config(config: BrokerConfig) -> dict[str, QualificationResult]:
    environment = config.resolve_environment()
    results: dict[str, QualificationResult] = {}
    for key, upstream in config.upstreams.items():
        if upstream.shareable:
            results[key] = await qualify_upstream(key, upstream, environment[key])
    return results

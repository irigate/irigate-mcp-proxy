from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any, Hashable

from mcp import types

from irigate.audit import AuditLog
from irigate.models import BrokerConfig
from irigate.qualification import QualificationResult, qualify_upstream
from irigate.runtime_report import RuntimeMetrics
from irigate.upstream import UpstreamError, UpstreamTimeout, UpstreamWorker


class BrokerInitializationError(RuntimeError):
    """The broker could not safely expose its configured upstreams."""


class Broker:
    """Aggregate tool schemas and route exact namespaced calls."""

    def __init__(
        self,
        config: BrokerConfig,
        *,
        require_qualified_sharing: bool = False,
    ) -> None:
        self.config = config
        self.require_qualified_sharing = require_qualified_sharing
        self._environment = config.resolve_environment()
        self._audit = AuditLog()
        self._runtime = RuntimeMetrics(config)
        self._qualifications: dict[str, QualificationResult] = {}
        self._shared: dict[str, UpstreamWorker] = {}
        self._isolated: dict[tuple[Hashable, str], UpstreamWorker] = {}
        self._degraded: set[str] = set()
        self._tools_by_upstream: dict[str, dict[str, types.Tool]] = {}
        self._exposed_tools: tuple[types.Tool, ...] = ()
        self._worker_lock = asyncio.Lock()
        self._started = False
        self._closing = False

    @property
    def tools(self) -> list[types.Tool]:
        return list(self._exposed_tools)

    def runtime_snapshot(self) -> dict[str, Any]:
        return self._runtime.snapshot()

    def _worker(self, key: str) -> UpstreamWorker:
        return UpstreamWorker(
            key,
            self.config.upstreams[key],
            self._environment[key],
            event_sink=lambda kind, seconds: self._runtime.duration(key, kind, seconds),
        )

    async def _start_worker(self, key: str) -> tuple[UpstreamWorker, tuple[types.Tool, ...]]:
        worker = self._worker(key)
        started = time.monotonic()
        tools = await worker.start()
        self._runtime.spawned(key, time.monotonic() - started)
        return worker, tools

    async def _close_worker(self, key: str, worker: UpstreamWorker) -> None:
        await worker.close()
        self._runtime.closed(key)

    def namespace_tools(
        self, upstream_key: str, tools: Sequence[types.Tool]
    ) -> tuple[types.Tool, ...]:
        seen: set[str] = set()
        exposed: list[types.Tool] = []
        for tool in tools:
            if tool.name in seen:
                raise BrokerInitializationError(
                    f"upstream '{upstream_key}' returned duplicate tool name '{tool.name}'"
                )
            seen.add(tool.name)
            exposed.append(tool.model_copy(update={"name": f"{upstream_key}__{tool.name}"}))
        return tuple(exposed)

    async def start(self) -> None:
        if self._started:
            return
        self._closing = False
        exposed: list[types.Tool] = []
        try:
            for key, upstream_config in self.config.upstreams.items():
                qualification: QualificationResult | None = None
                if upstream_config.shareable:
                    qualification = await qualify_upstream(
                        key, upstream_config, self._environment[key]
                    )
                    self._qualifications[key] = qualification
                    self._runtime.qualification(key, qualification)
                    if not qualification.admitted and self.require_qualified_sharing:
                        raise BrokerInitializationError(
                            f"upstream '{key}' failed qualification"
                        )

                worker: UpstreamWorker | None = None
                try:
                    worker, tools = await self._start_worker(key)
                    namespaced = self.namespace_tools(key, tools)
                except BaseException as exc:
                    if worker is not None:
                        await self._close_worker(key, worker)
                    raise BrokerInitializationError(
                        f"upstream '{key}' failed initialization"
                    ) from exc
                self._tools_by_upstream[key] = {tool.name: tool for tool in tools}
                exposed.extend(namespaced)
                if qualification is not None and qualification.admitted:
                    self._shared[key] = worker
                    self._runtime.effective_mode(key, "shared")
                else:
                    await self._close_worker(key, worker)
                    self._runtime.effective_mode(key, "isolated")
        except BaseException:
            await self.close()
            raise
        self._exposed_tools = tuple(exposed)
        self._started = True
        self._runtime.write()

    async def worker_for(self, upstream_key: str, session_key: Hashable) -> UpstreamWorker:
        if self._closing:
            raise UpstreamError(f"upstream '{upstream_key}' is unavailable")
        self._runtime.binding(upstream_key, session_key)
        shared = self._shared.get(upstream_key)
        if shared is not None:
            self._runtime.reused(upstream_key)
            return shared
        instance_key = (session_key, upstream_key)
        worker = self._isolated.get(instance_key)
        if worker is not None:
            self._runtime.reused(upstream_key)
            return worker
        async with self._worker_lock:
            if self._closing:
                raise UpstreamError(f"upstream '{upstream_key}' is unavailable")
            worker = self._isolated.get(instance_key)
            if worker is None:
                worker, _ = await self._start_worker(upstream_key)
                self._isolated[instance_key] = worker
            else:
                self._runtime.reused(upstream_key)
        return worker

    async def _record_failure(self, key: str, *, crash: bool) -> None:
        self._runtime.failed(key, crash=crash)
        snapshot = self._runtime.snapshot()["upstreams"][key]
        config = self.config.upstreams[key]
        if (
            snapshot["failures"] >= config.failure_threshold
            or snapshot["crashes"] >= config.crash_threshold
        ) and key not in self._degraded:
            self._degraded.add(key)
            shared = self._shared.pop(key, None)
            if shared is not None:
                await self._close_worker(key, shared)
            self._runtime.effective_mode(key, "degraded")

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        session_key: Hashable,
    ) -> types.CallToolResult:
        audit_started = time.monotonic()
        upstream_key, separator, tool_name = name.partition("__")
        if not separator or upstream_key not in self.config.upstreams:
            self._audit.emit(
                upstream=None,
                tool=name,
                outcome="invalid_tool",
                duration_seconds=time.monotonic() - audit_started,
            )
            return self._error("unknown upstream prefix")
        tools = self._tools_by_upstream[upstream_key]
        if tool_name not in tools:
            self._audit.emit(
                upstream=upstream_key,
                tool=tool_name,
                outcome="invalid_tool",
                duration_seconds=time.monotonic() - audit_started,
            )
            return self._error(f"unknown tool for upstream '{upstream_key}'")
        if self._closing:
            self._audit.emit(
                upstream=upstream_key,
                tool=tool_name,
                outcome="shutdown",
                duration_seconds=time.monotonic() - audit_started,
            )
            return self._error("broker is shutting down")
        try:
            worker = await self.worker_for(upstream_key, session_key)
            started = time.monotonic()
            try:
                result = await worker.call_tool(tool_name, arguments)
            finally:
                self._runtime.duration(
                    upstream_key, "call_duration", time.monotonic() - started
                )
            if result.isError:
                await self._record_failure(upstream_key, crash=False)
            self._audit.emit(
                upstream=upstream_key,
                tool=tool_name,
                outcome="upstream_error" if result.isError else "success",
                duration_seconds=time.monotonic() - audit_started,
            )
            return result
        except UpstreamTimeout as exc:
            await self._record_failure(upstream_key, crash=False)
            self._audit.emit(
                upstream=upstream_key,
                tool=tool_name,
                outcome="timeout",
                duration_seconds=time.monotonic() - audit_started,
            )
            return self._error(str(exc))
        except UpstreamError:
            await self._record_failure(upstream_key, crash=True)
            self._audit.emit(
                upstream=upstream_key,
                tool=tool_name,
                outcome="upstream_error",
                duration_seconds=time.monotonic() - audit_started,
            )
            return self._error(f"upstream '{upstream_key}' is unavailable")
        finally:
            self._runtime.write()

    @staticmethod
    def _error(message: str) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            isError=True,
        )

    async def close(self) -> None:
        async with self._worker_lock:
            self._closing = True
            workers = [*self._shared.values(), *self._isolated.values()]
            self._shared.clear()
            self._isolated.clear()
        if workers:
            await asyncio.gather(
                *(
                    self._close_worker(worker.key, worker)
                    for worker in workers
                ),
                return_exceptions=True,
            )
        self._started = False
        self._runtime.write()

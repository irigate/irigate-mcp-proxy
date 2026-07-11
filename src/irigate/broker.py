from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any, Hashable

from mcp import types

from irigate.audit import AuditLog
from irigate.config import ConfigurationError
from irigate.models import BrokerConfig
from irigate.qualification import QualificationResult, qualify_upstream
from irigate.runtime_report import RuntimeMetrics
from irigate.selection import Selection, ToolSelection
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
        self._reload_lock = asyncio.Lock()
        self._activation_locks: dict[str, asyncio.Lock] = {}
        self._started = False
        self._closing = False

    @property
    def tools(self) -> list[types.Tool]:
        return list(self._exposed_tools)

    def runtime_snapshot(self) -> dict[str, Any]:
        return self._runtime.snapshot()

    def _worker(
        self,
        key: str,
        *,
        config: BrokerConfig | None = None,
        environment: dict[str, dict[str, str]] | None = None,
    ) -> UpstreamWorker:
        selected_config = self.config if config is None else config
        selected_environment = self._environment if environment is None else environment
        return UpstreamWorker(
            key,
            selected_config.upstreams[key],
            selected_environment[key],
            event_sink=lambda kind, seconds: self._runtime.duration(key, kind, seconds),
            idle_sink=lambda worker: self._idle_closed(key, worker),
        )

    def _idle_closed(self, key: str, worker: UpstreamWorker) -> None:
        if self._shared.get(key) is worker:
            del self._shared[key]
        for instance_key, isolated in list(self._isolated.items()):
            if isolated is worker:
                del self._isolated[instance_key]
        if worker.account_close():
            self._runtime.closed(key)
            self._runtime.write()

    async def _start_worker(self, key: str) -> tuple[UpstreamWorker, tuple[types.Tool, ...]]:
        worker = self._worker(key)
        started = time.monotonic()
        tools = await worker.start()
        worker.account_spawn()
        self._runtime.spawned(key, time.monotonic() - started)
        return worker, tools

    async def _close_worker(self, key: str, worker: UpstreamWorker) -> None:
        await worker.close()
        if worker.account_close():
            self._runtime.closed(key)

    async def _prepare_upstream(
        self,
        key: str,
        config: BrokerConfig,
        environment: dict[str, dict[str, str]],
    ) -> tuple[QualificationResult | None, UpstreamWorker | None, tuple[types.Tool, ...]]:
        upstream_config = config.upstreams[key]
        qualification: QualificationResult | None = None
        if upstream_config.shareable:
            try:
                qualification = await qualify_upstream(
                    key, upstream_config, environment[key]
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise BrokerInitializationError(
                    f"upstream '{key}' failed qualification"
                ) from exc
            if not qualification.admitted and self.require_qualified_sharing:
                raise BrokerInitializationError(f"upstream '{key}' failed qualification")

        worker = self._worker(key, config=config, environment=environment)
        try:
            started = time.monotonic()
            tools = await worker.start()
            worker.account_spawn()
            self._runtime.spawned(key, time.monotonic() - started)
            self.namespace_tools(key, tools)
        except BaseException as exc:
            await self._close_worker(key, worker)
            raise BrokerInitializationError(
                f"upstream '{key}' failed initialization"
            ) from exc

        if qualification is not None and qualification.admitted:
            return qualification, worker, tools
        await self._close_worker(key, worker)
        return qualification, None, tools

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
        self._started = True
        self._runtime.write()

    async def _activate(self, key: str) -> None:
        if key in self._tools_by_upstream:
            return
        lock = self._activation_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._tools_by_upstream:
                return
            qualification, worker, tools = await self._prepare_upstream(
                key, self.config, self._environment
            )
            self._tools_by_upstream[key] = {tool.name: tool for tool in tools}
            if qualification is None:
                self._runtime.effective_mode(key, "isolated")
            else:
                self._qualifications[key] = qualification
                self._runtime.qualification(key, qualification)
                if worker is not None:
                    self._shared[key] = worker
                    self._runtime.effective_mode(key, "shared")
                else:
                    self._runtime.effective_mode(key, "isolated")
            self._runtime.write()

    async def list_tools(self, selection: Selection) -> list[types.Tool]:
        for key in self.config.upstreams:
            if key in selection.upstreams:
                await self._activate(key)
        exposed = [
            tool
            for key in self.config.upstreams
            if key in selection.upstreams
            for tool in self.namespace_tools(
                key, tuple(self._tools_by_upstream[key].values())
            )
        ]
        if isinstance(selection, ToolSelection):
            missing = sorted(selection.tools - {tool.name for tool in exposed})
            if missing:
                raise BrokerInitializationError(
                    "selected tools are unavailable: " + ", ".join(missing)
                )
            exposed = [tool for tool in exposed if tool.name in selection.tools]
        return exposed

    async def worker_for(self, upstream_key: str, session_key: Hashable) -> UpstreamWorker:
        await self._activate(upstream_key)
        if self._closing:
            raise UpstreamError(f"upstream '{upstream_key}' is unavailable")
        self._runtime.binding(upstream_key, session_key)
        shared = self._shared.get(upstream_key)
        if shared is not None and shared.is_running:
            self._runtime.reused(upstream_key)
            return shared
        instance_key = (session_key, upstream_key)
        worker = self._isolated.get(instance_key)
        if worker is not None and worker.is_running:
            self._runtime.reused(upstream_key)
            return worker
        async with self._worker_lock:
            if self._closing:
                raise UpstreamError(f"upstream '{upstream_key}' is unavailable")
            if upstream_key not in self.config.upstreams:
                raise UpstreamError(f"upstream '{upstream_key}' is unavailable")
            shared = self._shared.get(upstream_key)
            if shared is not None and shared.is_running:
                self._runtime.reused(upstream_key)
                return shared
            qualification = self._qualifications.get(upstream_key)
            if (
                qualification is not None
                and qualification.admitted
                and upstream_key not in self._degraded
            ):
                worker, _ = await self._start_worker(upstream_key)
                self._shared[upstream_key] = worker
                return worker
            worker = self._isolated.get(instance_key)
            if worker is None or not worker.is_running:
                worker, _ = await self._start_worker(upstream_key)
                self._isolated[instance_key] = worker
            else:
                self._runtime.reused(upstream_key)
            return worker

    async def reload(self, config: BrokerConfig) -> bool:
        """Atomically adopt changed upstreams without replacing downstream sessions."""

        if config.host != self.config.host or config.port != self.config.port:
            raise ConfigurationError("host and port cannot change while the broker is running")

        async with self._reload_lock:
            old_config = self.config
            changed = {
                key
                for key in old_config.upstreams.keys() & config.upstreams.keys()
                if old_config.upstreams[key] != config.upstreams[key]
            }
            added = config.upstreams.keys() - old_config.upstreams.keys()
            removed = old_config.upstreams.keys() - config.upstreams.keys()
            if not changed and not added and not removed and config == old_config:
                return False

            environment = config.resolve_environment()
            prepared: dict[
                str,
                tuple[QualificationResult | None, UpstreamWorker | None, tuple[types.Tool, ...]],
            ] = {}
            try:
                for key in config.upstreams:
                    if key in changed and key in self._tools_by_upstream:
                        upstream = config.upstreams[key]
                        self._runtime.ensure_upstream(
                            key, upstream.shareable, upstream.qualifier
                        )
                        prepared[key] = await self._prepare_upstream(key, config, environment)
            except BaseException:
                await asyncio.gather(
                    *(
                        self._close_worker(key, worker)
                        for key, (_, worker, _) in prepared.items()
                        if worker is not None
                    ),
                    return_exceptions=True,
                )
                raise

            retired: list[tuple[str, UpstreamWorker]] = []
            async with self._worker_lock:
                affected = changed | removed
                for key in affected:
                    shared = self._shared.pop(key, None)
                    if shared is not None:
                        retired.append((key, shared))
                for instance_key, worker in list(self._isolated.items()):
                    if instance_key[1] in affected:
                        retired.append((instance_key[1], worker))
                        del self._isolated[instance_key]

                self.config = config
                self._environment = environment
                self._runtime.reconfigure(config)
                for key in removed:
                    self._tools_by_upstream.pop(key, None)
                    self._qualifications.pop(key, None)
                    self._degraded.discard(key)
                    self._activation_locks.pop(key, None)
                for key in changed - prepared.keys():
                    self._tools_by_upstream.pop(key, None)
                    self._qualifications.pop(key, None)
                    self._degraded.discard(key)
                for key, (qualification, worker, tools) in prepared.items():
                    self._tools_by_upstream[key] = {tool.name: tool for tool in tools}
                    if qualification is None:
                        self._qualifications.pop(key, None)
                        self._runtime.effective_mode(key, "isolated")
                    else:
                        self._qualifications[key] = qualification
                        self._runtime.qualification(key, qualification)
                    if worker is not None:
                        self._shared[key] = worker
                        self._runtime.effective_mode(key, "shared")
                    self._degraded.discard(key)
                self._exposed_tools = tuple(
                    exposed
                    for key in config.upstreams
                    if key in self._tools_by_upstream
                    for exposed in self.namespace_tools(
                        key, tuple(self._tools_by_upstream[key].values())
                    )
                )

            if retired:
                await asyncio.gather(
                    *(self._close_worker(key, worker) for key, worker in retired),
                    return_exceptions=True,
                )
            self._runtime.write()
            return True

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
        selection: Selection | None = None,
        *,
        agent: str = "anonymous",
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
        if selection is not None and (
            upstream_key not in selection.upstreams
            or (isinstance(selection, ToolSelection) and name not in selection.tools)
        ):
            self._audit.emit(
                upstream=upstream_key,
                tool=tool_name,
                outcome="invalid_tool",
                duration_seconds=time.monotonic() - audit_started,
            )
            return self._error("tool is not included in this agent selection")
        await self._activate(upstream_key)
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
        self._runtime.agent_call(agent, upstream_key)
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
                self._runtime.agent_failed(agent, upstream_key)
            self._audit.emit(
                upstream=upstream_key,
                tool=tool_name,
                outcome="upstream_error" if result.isError else "success",
                duration_seconds=time.monotonic() - audit_started,
            )
            return result
        except UpstreamTimeout as exc:
            await self._record_failure(upstream_key, crash=False)
            self._runtime.agent_failed(agent, upstream_key)
            self._audit.emit(
                upstream=upstream_key,
                tool=tool_name,
                outcome="timeout",
                duration_seconds=time.monotonic() - audit_started,
            )
            return self._error(str(exc))
        except UpstreamError:
            await self._record_failure(upstream_key, crash=True)
            self._runtime.agent_failed(agent, upstream_key)
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

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Hashable

from mcp import types

from irigate.models import BrokerConfig
from irigate.upstream import UpstreamError, UpstreamTimeout, UpstreamWorker


class BrokerInitializationError(RuntimeError):
    """The broker could not safely expose its configured upstreams."""


class Broker:
    """Aggregate tool schemas and route exact namespaced calls."""

    def __init__(self, config: BrokerConfig) -> None:
        self.config = config
        self._environment = config.resolve_environment()
        self._shared: dict[str, UpstreamWorker] = {}
        self._isolated: dict[tuple[Hashable, str], UpstreamWorker] = {}
        self._tools_by_upstream: dict[str, dict[str, types.Tool]] = {}
        self._exposed_tools: tuple[types.Tool, ...] = ()
        self._worker_lock = asyncio.Lock()
        self._started = False

    @property
    def tools(self) -> list[types.Tool]:
        return list(self._exposed_tools)

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
        exposed: list[types.Tool] = []
        try:
            for key, upstream_config in self.config.upstreams.items():
                worker = UpstreamWorker(key, upstream_config, self._environment[key])
                try:
                    tools = await worker.start()
                    namespaced = self.namespace_tools(key, tools)
                except BaseException as exc:
                    await worker.close()
                    raise BrokerInitializationError(
                        f"upstream '{key}' failed initialization"
                    ) from exc
                self._tools_by_upstream[key] = {tool.name: tool for tool in tools}
                exposed.extend(namespaced)
                if upstream_config.shareable:
                    self._shared[key] = worker
                else:
                    await worker.close()
        except BaseException:
            await self.close()
            raise
        self._exposed_tools = tuple(exposed)
        self._started = True

    async def worker_for(self, upstream_key: str, session_key: Hashable) -> UpstreamWorker:
        shared = self._shared.get(upstream_key)
        if shared is not None:
            return shared
        instance_key = (session_key, upstream_key)
        worker = self._isolated.get(instance_key)
        if worker is not None:
            return worker
        async with self._worker_lock:
            worker = self._isolated.get(instance_key)
            if worker is None:
                upstream_config = self.config.upstreams[upstream_key]
                worker = UpstreamWorker(
                    upstream_key, upstream_config, self._environment[upstream_key]
                )
                await worker.start()
                self._isolated[instance_key] = worker
        return worker

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        session_key: Hashable,
    ) -> types.CallToolResult:
        upstream_key, separator, tool_name = name.partition("__")
        if not separator or upstream_key not in self.config.upstreams:
            return self._error("unknown upstream prefix")
        tools = self._tools_by_upstream[upstream_key]
        if tool_name not in tools:
            return self._error(f"unknown tool for upstream '{upstream_key}'")
        try:
            worker = await self.worker_for(upstream_key, session_key)
            return await worker.call_tool(tool_name, arguments)
        except UpstreamTimeout as exc:
            return self._error(str(exc))
        except UpstreamError:
            return self._error(f"upstream '{upstream_key}' is unavailable")

    @staticmethod
    def _error(message: str) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            isError=True,
        )

    async def close(self) -> None:
        workers = [*self._shared.values(), *self._isolated.values()]
        self._shared.clear()
        self._isolated.clear()
        if workers:
            await asyncio.gather(*(worker.close() for worker in workers), return_exceptions=True)
        self._started = False

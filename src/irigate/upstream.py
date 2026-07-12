from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from irigate.models import UpstreamConfig


class UpstreamError(RuntimeError):
    """An upstream failed without exposing its command, environment, or payload."""


class UpstreamTimeout(UpstreamError):
    pass


@dataclass(slots=True)
class _Call:
    tool: str
    arguments: dict[str, Any]
    result: asyncio.Future[types.CallToolResult]
    enqueued_at: float


class UpstreamWorker:
    """Own one stdio process and serialize requests through its MCP session."""

    def __init__(
        self,
        key: str,
        config: UpstreamConfig,
        environment: dict[str, str],
        inputs: Mapping[str, str] | None = None,
        event_sink: Callable[[str, float], None] | None = None,
        idle_sink: Callable[[UpstreamWorker], None] | None = None,
        activity_sink: Callable[[str], None] | None = None,
    ) -> None:
        self.key = key
        self.config = config
        self.environment = environment
        self.inputs = dict(inputs or {})
        self._event_sink = event_sink
        self._idle_sink = idle_sink
        self._activity_sink = activity_sink
        self.tools: tuple[types.Tool, ...] = ()
        self._queue: asyncio.Queue[_Call | None] = asyncio.Queue()
        self._ready: asyncio.Future[tuple[types.Tool, ...]] | None = None
        self._task: asyncio.Task[None] | None = None
        self._active_results: set[asyncio.Future[types.CallToolResult]] = set()
        self._parallel_tasks: set[asyncio.Task[None]] = set()
        self._live_accounted = False

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def account_spawn(self) -> None:
        self._live_accounted = True

    def account_close(self) -> bool:
        if not self._live_accounted:
            return False
        self._live_accounted = False
        return True

    async def start(self) -> tuple[types.Tool, ...]:
        if self._task is not None:
            return self.tools
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._run(), name=f"irigate-upstream-{self.key}")
        try:
            self.tools = await self._ready
        except BaseException:
            await self.close()
            raise
        return self.tools

    async def _run(self) -> None:
        assert self._ready is not None
        try:
            placeholder = "{" + "|".join(self.config.workspace_sources) + "}"
            args = [
                self.inputs["workspace"] if arg == placeholder else arg
                for arg in self.config.args
            ]
            params = StdioServerParameters(
                command=self.config.command,
                args=args,
                cwd=self.config.cwd,
                env=self.environment,
            )
            async with stdio_client(params) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    tools = tuple(listed.tools)
                    if not self._ready.done():
                        self._ready.set_result(tools)
                    while True:
                        try:
                            request = await asyncio.wait_for(
                                self._queue.get(),
                                timeout=self.config.idle_timeout_seconds,
                            )
                        except asyncio.TimeoutError:
                            if self._parallel_tasks:
                                continue
                            if self._idle_sink is not None:
                                self._idle_sink(self)
                            return
                        if request is None:
                            if self._parallel_tasks:
                                await asyncio.gather(
                                    *self._parallel_tasks, return_exceptions=True
                                )
                            return
                        if self.config.concurrency == "parallel":
                            task = asyncio.create_task(
                                self._execute_call(session, request),
                                name=f"irigate-call-{self.key}",
                            )
                            self._parallel_tasks.add(task)
                            task.add_done_callback(self._parallel_tasks.discard)
                        else:
                            await self._execute_call(session, request)
        except BaseException as exc:
            safe_error = UpstreamError(f"upstream '{self.key}' is unavailable")
            if not self._ready.done():
                self._ready.set_exception(safe_error)
            for result in self._active_results:
                if not result.done():
                    result.set_exception(safe_error)
            while not self._queue.empty():
                pending = self._queue.get_nowait()
                if pending is not None and not pending.result.done():
                    pending.result.set_exception(safe_error)
            if isinstance(exc, asyncio.CancelledError):
                raise

    async def _execute_call(self, session: ClientSession, request: _Call) -> None:
        self._active_results.add(request.result)
        if self._activity_sink is not None:
            self._activity_sink("started")
        if self._event_sink is not None:
            self._event_sink("queue_duration", time.monotonic() - request.enqueued_at)
        try:
            result = await session.call_tool(request.tool, request.arguments)
        except BaseException as exc:
            if not request.result.done():
                request.result.set_exception(
                    UpstreamError(f"upstream '{self.key}' call failed")
                )
            if isinstance(exc, asyncio.CancelledError):
                raise
        else:
            if not request.result.done():
                request.result.set_result(result)
        finally:
            self._active_results.discard(request.result)
            if self._activity_sink is not None:
                self._activity_sink("finished")

    async def call_tool(
        self, tool: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        if self._task is None or self._task.done():
            raise UpstreamError(f"upstream '{self.key}' is unavailable")
        result: asyncio.Future[types.CallToolResult] = asyncio.get_running_loop().create_future()
        await self._queue.put(
            _Call(
                tool=tool,
                arguments=arguments,
                result=result,
                enqueued_at=time.monotonic(),
            )
        )
        try:
            return await asyncio.wait_for(
                asyncio.shield(result), timeout=self.config.call_timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            result.cancel()
            raise UpstreamTimeout(f"upstream '{self.key}' call timed out") from exc

    async def close(self) -> None:
        task = self._task
        if task is None:
            return
        if not task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(task, timeout=5)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        else:
            await asyncio.gather(task, return_exceptions=True)
        self._task = None

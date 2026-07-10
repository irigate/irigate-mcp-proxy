from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

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


class UpstreamWorker:
    """Own one stdio process and serialize requests through its MCP session."""

    def __init__(
        self,
        key: str,
        config: UpstreamConfig,
        environment: dict[str, str],
    ) -> None:
        self.key = key
        self.config = config
        self.environment = environment
        self.tools: tuple[types.Tool, ...] = ()
        self._queue: asyncio.Queue[_Call | None] = asyncio.Queue()
        self._ready: asyncio.Future[tuple[types.Tool, ...]] | None = None
        self._task: asyncio.Task[None] | None = None
        self._current: asyncio.Future[types.CallToolResult] | None = None

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
        params = StdioServerParameters(
            command=self.config.command,
            args=list(self.config.args),
            env=self.environment,
        )
        try:
            async with stdio_client(params) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    tools = tuple(listed.tools)
                    if not self._ready.done():
                        self._ready.set_result(tools)
                    while True:
                        request = await self._queue.get()
                        if request is None:
                            return
                        self._current = request.result
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
                            self._current = None
        except BaseException as exc:
            safe_error = UpstreamError(f"upstream '{self.key}' is unavailable")
            if not self._ready.done():
                self._ready.set_exception(safe_error)
            if self._current is not None and not self._current.done():
                self._current.set_exception(safe_error)
            while not self._queue.empty():
                pending = self._queue.get_nowait()
                if pending is not None and not pending.result.done():
                    pending.result.set_exception(safe_error)
            if isinstance(exc, asyncio.CancelledError):
                raise

    async def call_tool(
        self, tool: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        if self._task is None or self._task.done():
            raise UpstreamError(f"upstream '{self.key}' is unavailable")
        result: asyncio.Future[types.CallToolResult] = asyncio.get_running_loop().create_future()
        await self._queue.put(_Call(tool=tool, arguments=arguments, result=result))
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

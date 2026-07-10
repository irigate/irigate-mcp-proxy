from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, ListToolsResult


@dataclass
class _Request:
    tool: str
    arguments: dict[str, Any]
    future: asyncio.Future[CallToolResult]


class UpstreamWorker:
    """Own one stdio session in an independently failing asyncio task."""

    def __init__(self, params: StdioServerParameters, timeout_seconds: float = 30.0) -> None:
        self.params = params
        self.timeout_seconds = timeout_seconds
        self._queue: asyncio.Queue[_Request | None] = asyncio.Queue()
        self._ready: asyncio.Future[ListToolsResult] | None = None
        self._task: asyncio.Task[None] | None = None
        self._active: _Request | None = None

    async def start(self) -> ListToolsResult:
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._run())
        return await asyncio.wait_for(self._ready, timeout=self.timeout_seconds)

    async def _run(self) -> None:
        assert self._ready is not None
        try:
            async with stdio_client(self.params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    self._ready.set_result(await session.list_tools())
                    while True:
                        request = await self._queue.get()
                        if request is None:
                            return
                        self._active = request
                        try:
                            result = await session.call_tool(request.tool, request.arguments)
                        except BaseException as exc:
                            if not request.future.done():
                                request.future.set_exception(RuntimeError(str(exc)))
                        else:
                            if not request.future.done():
                                request.future.set_result(result)
                        finally:
                            self._active = None
        except BaseException as exc:
            error = RuntimeError(f"upstream worker stopped: {exc}")
            if not self._ready.done():
                self._ready.set_exception(error)
            if self._active is not None and not self._active.future.done():
                self._active.future.set_exception(error)
            while not self._queue.empty():
                queued = self._queue.get_nowait()
                if queued is not None and not queued.future.done():
                    queued.future.set_exception(error)

    async def call(self, tool: str, arguments: dict[str, Any]) -> CallToolResult:
        if self._task is None or self._task.done():
            raise RuntimeError("upstream worker is not running")
        future: asyncio.Future[CallToolResult] = asyncio.get_running_loop().create_future()
        await self._queue.put(_Request(tool, arguments, future))
        return await asyncio.wait_for(future, timeout=self.timeout_seconds)

    async def close(self) -> None:
        if self._task is None:
            return
        if not self._task.done():
            await self._queue.put(None)
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except (asyncio.TimeoutError, BaseException):
            if not self._task.done():
                self._task.cancel()

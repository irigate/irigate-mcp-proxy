from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from irigate import __version__
from irigate.broker import Broker
from irigate.models import BrokerConfig


class _StreamableHTTPApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._manager.handle_request(scope, receive, send)


def create_app(
    config: BrokerConfig, *, require_qualified_sharing: bool = False
) -> Starlette:
    """Create the loopback Streamable HTTP app without starting processes."""

    broker = Broker(
        config, require_qualified_sharing=require_qualified_sharing
    )
    server: Server[Any] = Server("irigate", version=__version__)

    @server.list_tools()
    async def list_tools():
        return broker.tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        session_key = id(server.request_context.session)
        return await broker.call_tool(name, arguments, session_key)

    origins = [f"http://127.0.0.1:{config.port}", f"http://localhost:{config.port}"]
    if config.host == "::1":
        origins.append(f"http://[::1]:{config.port}")
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            f"127.0.0.1:{config.port}",
            f"localhost:{config.port}",
            f"[::1]:{config.port}",
        ],
        allowed_origins=origins,
    )
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=False,
        security_settings=security,
    )
    endpoint = _StreamableHTTPApp(manager)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        await broker.start()
        try:
            async with manager.run():
                yield
        finally:
            await broker.close()

    return Starlette(routes=[Route("/mcp", endpoint=endpoint)], lifespan=lifespan)

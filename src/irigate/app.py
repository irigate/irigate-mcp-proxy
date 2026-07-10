from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from irigate import __version__
from irigate.broker import Broker, BrokerInitializationError
from irigate.config import ConfigurationError, load_config
from irigate.models import BrokerConfig

logger = logging.getLogger(__name__)


class _StreamableHTTPApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._manager.handle_request(scope, receive, send)


def create_app(
    config: BrokerConfig,
    *,
    require_qualified_sharing: bool = False,
    config_path: str | Path | None = None,
    reload_interval_seconds: float = 0.5,
) -> Starlette:
    """Create the loopback Streamable HTTP app without starting processes."""

    broker = Broker(
        config, require_qualified_sharing=require_qualified_sharing
    )
    watched_path = Path(config_path) if config_path is not None else None
    if watched_path is not None:
        try:
            initial_stat = watched_path.stat()
            initial_signature = (
                initial_stat.st_mtime_ns,
                initial_stat.st_size,
                initial_stat.st_ino,
            )
        except OSError:
            initial_signature = None
    else:
        initial_signature = None
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

    async def watch_config() -> None:
        assert watched_path is not None
        signature = initial_signature
        while True:
            await asyncio.sleep(reload_interval_seconds)
            try:
                current = watched_path.stat()
                current_signature = (current.st_mtime_ns, current.st_size, current.st_ino)
            except OSError:
                current_signature = None
            if current_signature == signature:
                continue
            signature = current_signature
            if current_signature is None:
                logger.error(
                    "configuration reload rejected: cannot read configuration: %s",
                    watched_path,
                )
                continue
            try:
                replacement = load_config(watched_path)
                if await broker.reload(replacement):
                    logger.info("configuration reloaded")
            except (ConfigurationError, BrokerInitializationError) as exc:
                logger.error("configuration reload rejected: %s", exc)
            except Exception:
                logger.exception("configuration reload failed")

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        await broker.start()
        watcher: asyncio.Task[None] | None = None
        if config_path is not None:
            watcher = asyncio.create_task(watch_config(), name="irigate-config-watcher")
        try:
            async with manager.run():
                yield
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            await broker.close()

    return Starlette(routes=[Route("/mcp", endpoint=endpoint)], lifespan=lifespan)

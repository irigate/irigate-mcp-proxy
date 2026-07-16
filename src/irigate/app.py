from __future__ import annotations

import asyncio
import logging
import re
import signal
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Callable

from mcp.server.lowlevel import Server
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.datastructures import Headers, QueryParams
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

from irigate import __version__
from irigate.broker import Broker, BrokerInitializationError
from irigate.config import ConfigurationError, load_config
from irigate.models import BrokerConfig, UpstreamConfig
from irigate.restart import RestartControl, remove_control, write_control
from irigate.selection import InputBindings, Selection, SelectionError, parse_selection

logger = logging.getLogger(__name__)
_request_selection: ContextVar[Selection | None] = ContextVar(
    "irigate_request_selection", default=None
)
_request_agent: ContextVar[str] = ContextVar("irigate_request_agent", default="anonymous")
_AGENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def current_selection() -> Selection:
    selection = _request_selection.get()
    if selection is None:
        raise RuntimeError("MCP request has no validated selector")
    return selection


def current_agent() -> str:
    return _request_agent.get()


class _StreamableHTTPApp:
    def __init__(
        self,
        manager: StreamableHTTPSessionManager,
        configured_upstreams: Callable[[], Mapping[str, UpstreamConfig]],
    ) -> None:
        self._manager = manager
        self._configured_upstreams = configured_upstreams
        self._session_inputs: dict[str, InputBindings] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            query = QueryParams(scope.get("query_string", b"").decode("utf-8"))
            agent_values = query.getlist("agent")
            if len(agent_values) > 1:
                raise SelectionError("repeated agent parameters are not allowed")
            agent = agent_values[0] if agent_values else "anonymous"
            if _AGENT_NAME.fullmatch(agent) is None:
                raise SelectionError("invalid agent name")
            selector_items = [item for item in query.multi_items() if item[0] != "agent"]
            selection = parse_selection(selector_items, self._configured_upstreams())
            session_id = Headers(scope=scope).get(MCP_SESSION_ID_HEADER)
            if (
                session_id in self._session_inputs
                and self._session_inputs[session_id] != selection.inputs
            ):
                raise SelectionError("session inputs cannot be changed")
        except (SelectionError, UnicodeDecodeError) as exc:
            message = str(exc) if isinstance(exc, SelectionError) else "invalid query string"
            response = JSONResponse({"error": message}, status_code=400)
            await response(scope, receive, send)
            return

        token: Token[Selection | None] = _request_selection.set(selection)
        agent_token = _request_agent.set(agent)

        async def bind_session_inputs(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] < 400:
                response_session_id = Headers(raw=message.get("headers", [])).get(
                    MCP_SESSION_ID_HEADER
                )
                if response_session_id is not None:
                    self._session_inputs.setdefault(response_session_id, selection.inputs)
            await send(message)

        try:
            await self._manager.handle_request(scope, receive, bind_session_inputs)
        finally:
            _request_agent.reset(agent_token)
            _request_selection.reset(token)


def create_app(
    config: BrokerConfig,
    *,
    require_qualified_sharing: bool = False,
    config_path: str | Path | None = None,
    reload_interval_seconds: float = 0.5,
    process_control: tuple[Path, RestartControl] | None = None,
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
    reload_requested = asyncio.Event()
    server: Server[Any] = Server("irigate", version=__version__)

    @server.list_tools()
    async def list_tools():
        return await broker.list_tools(current_selection())

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        session_key = id(server.request_context.session)
        return await broker.call_tool(
            name, arguments, session_key, current_selection(), agent=current_agent()
        )

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
    endpoint = _StreamableHTTPApp(manager, lambda: broker.config.upstreams)

    async def watch_config() -> None:
        assert watched_path is not None
        signature = initial_signature
        while True:
            forced = False
            try:
                await asyncio.wait_for(
                    reload_requested.wait(), timeout=reload_interval_seconds
                )
            except TimeoutError:
                pass
            else:
                reload_requested.clear()
                forced = True
            try:
                current = watched_path.stat()
                current_signature = (current.st_mtime_ns, current.st_size, current.st_ino)
            except OSError:
                current_signature = None
            if current_signature == signature and not forced:
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
        reload_signal_installed = False
        control_written = False
        if config_path is not None:
            watcher = asyncio.create_task(watch_config(), name="irigate-config-watcher")
            try:
                asyncio.get_running_loop().add_signal_handler(
                    signal.SIGHUP, reload_requested.set
                )
                reload_signal_installed = True
            except (NotImplementedError, RuntimeError):
                logger.warning("SIGHUP reload control is unavailable on this event loop")
        try:
            async with manager.run():
                if process_control is not None:
                    write_control(*process_control)
                    control_written = True
                yield
        finally:
            if reload_signal_installed:
                asyncio.get_running_loop().remove_signal_handler(signal.SIGHUP)
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            await broker.close()
            if process_control is not None and control_written:
                path, control = process_control
                remove_control(path, control.instance_id)

    return Starlette(routes=[Route("/mcp", endpoint=endpoint)], lifespan=lifespan)

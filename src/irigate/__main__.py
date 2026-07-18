from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import uvicorn
from mcp import types

from irigate import __version__
from irigate.app import create_app
from irigate.broker import Broker, BrokerInitializationError
from irigate.config import ConfigurationError, load_config
from irigate.logs import McpCallLog, iter_log, latest_log, log_directory
from irigate.migration import (
    MigrationError,
    discover_configurations,
    migrate_configurations,
)
from irigate.models import BrokerConfig
from irigate.qualification import qualify_config
from irigate.restart import (
    CONTROL_SCHEMA_VERSION,
    RestartControl,
    RestartError,
    control_path,
    reload_running,
    stop_running,
)
from irigate.selection import SelectionError, parse_selection


CONFIG_ENVIRONMENT_VARIABLE = "IRIGATE_CONFIG"
DEFAULT_CONFIG_PATH = Path("~/.config/irigate/config.yaml")
CONFIG_PATH_HELP = (
    f"YAML profile path (default file: {DEFAULT_CONFIG_PATH}; "
    f"{CONFIG_ENVIRONMENT_VARIABLE} overrides it)"
)


def resolve_config_path(argument: str | None) -> Path:
    configured = argument or os.environ.get(CONFIG_ENVIRONMENT_VARIABLE)
    return Path(configured).expanduser() if configured else DEFAULT_CONFIG_PATH.expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="irigate", description=f"Irigate {__version__} local MCP broker"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--config",
        help=CONFIG_PATH_HELP,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration without starting upstreams",
    )
    parser.add_argument(
        "--require-qualified-sharing",
        action="store_true",
        help="abort startup instead of downgrading failed sharing",
    )
    subcommands = parser.add_subparsers(dest="command")
    qualify = subcommands.add_parser(
        "qualify", help="qualify requested sharing without serving clients"
    )
    qualify.add_argument(
        "--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP
    )
    tools = subcommands.add_parser(
        "tools", help="start configured upstreams and list namespaced tools"
    )
    tools.add_argument("--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP)
    tools.add_argument("--upstream", help="discover only this configured upstream")
    tools.add_argument(
        "--json",
        action="store_true",
        help="print tool names and descriptions as JSON",
    )
    upstreams = subcommands.add_parser(
        "upstreams", help="list configured upstream metadata without starting processes"
    )
    upstreams.add_argument("--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP)
    upstreams.add_argument("--json", action="store_true", help="print metadata as JSON")
    schema = subcommands.add_parser("schema", help="print one exact namespaced tool schema")
    schema.add_argument("--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP)
    schema.add_argument("tool", help="exact namespaced tool name")
    call = subcommands.add_parser("call", help="call one namespaced MCP tool")
    call.add_argument("--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP)
    call.add_argument("tool", help="namespaced tool name")
    call.add_argument(
        "--arguments",
        default="{}",
        metavar="JSON",
        help="tool arguments as a JSON object (default: {})",
    )
    ps = subcommands.add_parser("ps", help="show MCP upstream and agent usage")
    ps.add_argument("--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP)
    ps.add_argument("--json", action="store_true", help="print the runtime report as JSON")
    logs = subcommands.add_parser("logs", help="print the latest MCP call log")
    logs.add_argument("--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP)
    logs.add_argument(
        "-f", "--follow", action="store_true", help="print appended log records live"
    )
    reload_command = subcommands.add_parser(
        "reload",
        help="request an immediate profile reload",
        description=f"Irigate {__version__}: request an immediate profile reload",
    )
    reload_command.add_argument(
        "--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP
    )
    stop = subcommands.add_parser(
        "stop",
        help="gracefully stop a running Irigate server",
        description=f"Irigate {__version__}: gracefully stop a running Irigate server",
    )
    stop.add_argument("--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP)
    subcommands.add_parser(
        "skill-path", help="print the bundled progressive-disclosure Agent Skill path"
    )
    migrate = subcommands.add_parser(
        "migrate", help="move installed agent stdio MCP servers behind Irigate"
    )
    migrate.add_argument("source", nargs="?", help="migrate only this agent configuration")
    migrate.add_argument("--config", default=argparse.SUPPRESS, help=CONFIG_PATH_HELP)
    migrate.add_argument(
        "--all", action="store_true", help="migrate every discovered configuration"
    )
    return parser


def select_migration_paths(source: str | None, migrate_all: bool) -> list[Path]:
    if source is not None:
        if migrate_all:
            raise MigrationError("a configuration file and --all cannot be combined")
        return [Path(source).expanduser()]
    candidates = discover_configurations()
    if not candidates:
        raise MigrationError("no supported AI-agent MCP configurations found")
    if migrate_all:
        return [candidate.path for candidate in candidates]
    if not sys.stdin.isatty():
        raise MigrationError("use --all or provide a configuration file")
    for index, candidate in enumerate(candidates, start=1):
        print(f"{index}. {candidate.agent}: {candidate.path}")
    raw = input("Select configurations (comma-separated numbers): ").strip()
    try:
        indexes = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError as exc:
        raise MigrationError("selection must contain comma-separated numbers") from exc
    if not indexes or min(indexes) < 1 or max(indexes) > len(candidates):
        raise MigrationError("selection is empty or out of range")
    return [candidate.path for index, candidate in enumerate(candidates, start=1) if index in indexes]


def configured_upstream_metadata(
    config: BrokerConfig,
) -> list[dict[str, str | None]]:
    return [
        {"name": key, "description": upstream.description}
        for key, upstream in config.upstreams.items()
    ]


async def discover_configured_tools(
    config: BrokerConfig, upstream: str | None = None
) -> list[types.Tool]:
    broker = Broker(config)
    await broker.start()
    try:
        query = () if upstream is None else (("upstreams", upstream),)
        selection = parse_selection(query, config.upstreams)
        return await broker.list_tools(selection)
    finally:
        await broker.close()


async def discover_configured_tool_schema(
    config: BrokerConfig, tool_name: str
) -> types.Tool:
    broker = Broker(config)
    await broker.start()
    try:
        selection = parse_selection((("tools", tool_name),), config.upstreams)
        tools = await broker.list_tools(selection)
        if len(tools) != 1 or tools[0].name != tool_name:
            raise BrokerInitializationError(f"tool '{tool_name}' is unavailable")
        return tools[0]
    finally:
        await broker.close()


async def call_configured_tool(
    config: BrokerConfig,
    tool: str,
    arguments: dict[str, object],
    *,
    call_log: McpCallLog | None = None,
) -> tuple[str, bool]:
    broker = Broker(config, call_log=call_log)
    await broker.start()
    try:
        result = await broker.call_tool(tool, arguments, "cli", agent="cli")
        return result.model_dump_json(exclude_none=True), result.isError is True
    finally:
        await broker.close()


def read_runtime_report(config: BrokerConfig) -> dict[str, object]:
    path = config.runtime_report_path
    if path is None:
        raise ValueError("profile has no runtime_report_path")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read runtime report: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid runtime report JSON: {path}") from exc
    if not isinstance(report, dict):
        raise ValueError(f"invalid runtime report document: {path}")
    return report


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, remainder = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def idle_duration(raw_upstream: dict[object, object]) -> str:
    if raw_upstream.get("activity_state") != "idle":
        return "-"
    idle_since = raw_upstream.get("idle_since")
    if not isinstance(idle_since, str):
        return "-"
    try:
        started = datetime.fromisoformat(idle_since)
    except ValueError:
        return "-"
    if started.tzinfo is None:
        return "-"
    return format_duration((datetime.now(timezone.utc) - started).total_seconds())


def format_process_report(report: dict[str, object]) -> str:
    upstreams = report.get("upstreams", {})
    agents = report.get("agents", {})
    if not isinstance(upstreams, dict) or not isinstance(agents, dict):
        raise ValueError("runtime report has invalid upstream or agent statistics")
    rows = []
    for key, raw_upstream in upstreams.items():
        if not isinstance(raw_upstream, dict):
            continue
        state = str(raw_upstream.get("activity_state", "unknown"))
        idle_for = idle_duration(raw_upstream)
        timeout = raw_upstream.get("idle_timeout_seconds")
        idle_timeout = (
            format_duration(float(timeout))
            if isinstance(timeout, (int, float))
            else "-"
        )
        agent_rows = []
        for name, raw_agent in agents.items():
            if not isinstance(raw_agent, dict):
                continue
            usage = raw_agent.get(key)
            if isinstance(usage, dict):
                agent_rows.append(
                    (
                        str(name),
                        str(usage.get("calls", 0)),
                        str(usage.get("failures", 0)),
                    )
                )
        duration = raw_upstream.get("call_duration", {})
        calls = str(duration.get("count", 0) if isinstance(duration, dict) else 0)
        if not agent_rows:
            agent_rows = [("-", calls, str(raw_upstream.get("failures", 0)))]
        for agent, agent_calls, agent_failures in agent_rows:
            rows.append(
                (
                    str(key),
                    str(raw_upstream.get("effective_mode", "unknown")),
                    str(raw_upstream.get("live_instances", 0)),
                    state,
                    idle_for,
                    idle_timeout,
                    agent,
                    agent_calls,
                    agent_failures,
                )
            )
    headers = (
        "UPSTREAM",
        "MODE",
        "INSTANCES",
        "STATE",
        "IDLE_FOR",
        "IDLE_TIMEOUT",
        "AGENT",
        "CALLS",
        "FAILURES",
    )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        if rows
        else len(headers[index])
        for index in range(len(headers))
    ]
    return "\n".join(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in (headers, *rows)
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = resolve_config_path(args.config)
    if args.command == "skill-path":
        print(Path(__file__).parent / "agent_skill")
        return 0
    if args.command == "migrate":
        try:
            paths = select_migration_paths(args.source, args.all)
            result = migrate_configurations(paths, profile_path=config_path)
        except MigrationError as exc:
            print(f"migration error: {exc}", file=sys.stderr)
            return 2
        for path in result.paths:
            print(f"migrated {path}")
        print(f"profile={result.profile_path}")
        print(f"upstreams={result.server_count}")
        return 0
    try:
        config = load_config(config_path)
        if args.command not in {"upstreams", "ps", "logs", "reload", "stop"}:
            config.resolve_environment()
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "qualify":
        results = asyncio.run(qualify_config(config))
        for key, result in results.items():
            status = "qualified" if result.admitted else "isolated"
            print(f"{key}={status}")
        return 0 if all(result.admitted for result in results.values()) else 1

    if args.command == "upstreams":
        upstreams = configured_upstream_metadata(config)
        if args.json:
            print(
                json.dumps(
                    {"profile": config.name, "upstreams": upstreams},
                    separators=(",", ":"),
                )
            )
        else:
            for upstream in upstreams:
                description = upstream["description"] or ""
                print(f"{upstream['name']}\t{description}".rstrip())
        return 0

    if args.command == "tools":
        try:
            discovered_tools = asyncio.run(
                discover_configured_tools(config, upstream=args.upstream)
            )
        except (BrokerInitializationError, SelectionError) as exc:
            print(f"tool discovery error: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    [
                        {"name": tool.name, "description": tool.description}
                        for tool in discovered_tools
                    ],
                    separators=(",", ":"),
                )
            )
        else:
            for tool in discovered_tools:
                print(tool.name)
        return 0

    if args.command == "schema":
        try:
            tool = asyncio.run(discover_configured_tool_schema(config, args.tool))
        except (BrokerInitializationError, SelectionError) as exc:
            print(f"schema discovery error: {exc}", file=sys.stderr)
            return 1
        print(tool.model_dump_json(exclude_none=True))
        return 0

    if args.command == "call":
        try:
            arguments = json.loads(args.arguments)
        except json.JSONDecodeError as exc:
            print(f"arguments error: invalid JSON: {exc.msg}", file=sys.stderr)
            return 2
        if not isinstance(arguments, dict):
            print("arguments error: JSON value must be an object", file=sys.stderr)
            return 2
        try:
            call_log = McpCallLog.start(
                config.name, directory=config.runtime_log_path
            )
            output, is_error = asyncio.run(
                call_configured_tool(config, args.tool, arguments, call_log=call_log)
            )
        except OSError as exc:
            print(f"logs error: cannot start MCP log: {exc}", file=sys.stderr)
            return 1
        except BrokerInitializationError as exc:
            print(f"tool call error: {exc}", file=sys.stderr)
            return 1
        print(output)
        return 1 if is_error else 0

    if args.command == "logs":
        try:
            path = latest_log(config.name, directory=config.runtime_log_path)
            for line in iter_log(path, follow=args.follow):
                print(line, end="", flush=True)
        except (FileNotFoundError, OSError) as exc:
            print(f"logs error: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            return 130
        return 0

    if args.command == "ps":
        try:
            report = read_runtime_report(config)
            output = (
                json.dumps(report, sort_keys=True)
                if args.json
                else format_process_report(report)
            )
        except ValueError as exc:
            print(f"runtime report error: {exc}", file=sys.stderr)
            return 1
        print(output)
        return 0

    if args.command == "stop":
        try:
            stop_running(
                control_path(config.runtime_report_path),
                expected_profile=config.name,
                expected_config_path=config_path.resolve(),
            )
        except RestartError as exc:
            print(f"stop error: {exc}", file=sys.stderr)
            return 1
        print("Irigate stopped")
        return 0

    if args.command == "reload":
        try:
            reload_running(
                control_path(config.runtime_report_path),
                expected_profile=config.name,
                expected_config_path=config_path.resolve(),
            )
        except RestartError as exc:
            print(f"reload error: {exc}", file=sys.stderr)
            return 1
        print("Irigate reload requested")
        return 0

    if args.check:
        upstreams = ",".join(config.upstreams)
        environment = ",".join(sorted(config.environment_names)) or "none"
        print(f"profile={config.name}")
        print(f"listen={config.host}:{config.port}")
        print(f"upstreams={upstreams}")
        print(f"environment={environment}")
        if config.runtime_report_path is not None:
            print(f"runtime_report={config.runtime_report_path}")
        print(f"logs={log_directory(config.name, config.runtime_log_path)}")
        return 0

    process_control = None
    if config.runtime_report_path is not None:
        control = RestartControl(
            schema_version=CONTROL_SCHEMA_VERSION,
            profile=config.name,
            config_path=str(config_path.resolve()),
            pid=os.getpid(),
            instance_id=uuid4().hex,
            version=__version__,
        )
        process_control = (control_path(config.runtime_report_path), control)
    try:
        call_log = McpCallLog.start(config.name, directory=config.runtime_log_path)
    except OSError as exc:
        print(f"logs error: cannot start MCP log: {exc}", file=sys.stderr)
        return 1
    uvicorn.run(
        create_app(
            config,
            require_qualified_sharing=args.require_qualified_sharing,
            config_path=config_path,
            process_control=process_control,
            call_log=call_log,
        ),
        host=config.host,
        port=config.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

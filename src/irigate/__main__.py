from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

import uvicorn

from irigate.app import create_app
from irigate.broker import Broker, BrokerInitializationError
from irigate.config import ConfigurationError, load_config
from irigate.models import BrokerConfig
from irigate.qualification import qualify_config
from irigate.selection import parse_selection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irigate")
    parser.add_argument("--config", help="YAML profile path")
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
    qualify.add_argument("--config", required=True, help="YAML profile path")
    tools = subcommands.add_parser(
        "tools", help="start configured upstreams and list namespaced tools"
    )
    tools.add_argument("--config", required=True, help="YAML profile path")
    call = subcommands.add_parser("call", help="call one namespaced MCP tool")
    call.add_argument("--config", required=True, help="YAML profile path")
    call.add_argument("tool", help="namespaced tool name")
    call.add_argument(
        "--arguments",
        default="{}",
        metavar="JSON",
        help="tool arguments as a JSON object (default: {})",
    )
    return parser


async def list_configured_tools(config: BrokerConfig) -> list[str]:
    broker = Broker(config)
    await broker.start()
    try:
        selection = parse_selection((), config.upstreams)
        return [tool.name for tool in await broker.list_tools(selection)]
    finally:
        await broker.close()


async def call_configured_tool(
    config: BrokerConfig, tool: str, arguments: dict[str, object]
) -> tuple[str, bool]:
    broker = Broker(config)
    await broker.start()
    try:
        result = await broker.call_tool(tool, arguments, "cli")
        return result.model_dump_json(exclude_none=True), result.isError is True
    finally:
        await broker.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.config is None:
        build_parser().error("--config is required")
    try:
        config = load_config(args.config)
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

    if args.command == "tools":
        try:
            tool_names = asyncio.run(list_configured_tools(config))
        except BrokerInitializationError as exc:
            print(f"tool discovery error: {exc}", file=sys.stderr)
            return 1
        for tool_name in tool_names:
            print(tool_name)
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
            output, is_error = asyncio.run(
                call_configured_tool(config, args.tool, arguments)
            )
        except BrokerInitializationError as exc:
            print(f"tool call error: {exc}", file=sys.stderr)
            return 1
        print(output)
        return 1 if is_error else 0

    if args.check:
        upstreams = ",".join(config.upstreams)
        environment = ",".join(sorted(config.environment_names)) or "none"
        print(f"profile={config.name}")
        print(f"listen={config.host}:{config.port}")
        print(f"upstreams={upstreams}")
        print(f"environment={environment}")
        if config.runtime_report_path is not None:
            print(f"runtime_report={config.runtime_report_path}")
        return 0

    uvicorn.run(
        create_app(
            config,
            require_qualified_sharing=args.require_qualified_sharing,
            config_path=args.config,
        ),
        host=config.host,
        port=config.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

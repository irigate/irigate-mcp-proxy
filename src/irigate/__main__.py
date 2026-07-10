from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

import uvicorn

from irigate.app import create_app
from irigate.config import ConfigurationError, load_config
from irigate.qualification import qualify_config


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
    return parser


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

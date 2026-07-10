from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from irigate.config import ConfigurationError, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irigate")
    parser.add_argument("--config", required=True, help="YAML profile path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration without starting upstreams",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        config.resolve_environment()
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if not args.check:
        print("broker runtime is not implemented; use --check", file=sys.stderr)
        return 2

    upstreams = ",".join(config.upstreams)
    environment = ",".join(sorted(config.environment_names)) or "none"
    print(f"profile={config.name}")
    print(f"listen={config.host}:{config.port}")
    print(f"upstreams={upstreams}")
    print(f"environment={environment}")
    if config.runtime_report_path is not None:
        print(f"runtime_report={config.runtime_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

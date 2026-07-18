from __future__ import annotations

import json
import os
import time
from collections.abc import Generator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp import types

MCP_LOG_KEEP_FILES = 10


def log_directory(
    profile: str, runtime_log_path: str | Path | None = None
) -> Path:
    """Return the configured or default directory that owns one profile's logs."""

    if runtime_log_path is not None:
        return Path(runtime_log_path).expanduser()
    return Path.home() / ".local" / "log" / "irigate" / profile


def _log_pattern(profile: str) -> str:
    return f"{profile}-*.jsonl"


class McpCallLog:
    """Write complete MCP tool requests and responses to one start-scoped file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def start(
        cls,
        profile: str,
        *,
        directory: str | Path | None = None,
        keep_files: int = MCP_LOG_KEEP_FILES,
    ) -> McpCallLog:
        if keep_files < 1:
            raise ValueError("keep_files must be positive")
        log_path = log_directory(profile, directory)
        log_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        log_path.chmod(0o700)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        path = log_path / f"{profile}-{timestamp}-{os.getpid()}-{uuid4().hex[:8]}.jsonl"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        cls._rotate(log_path, profile, keep_files)
        return cls(path)

    @staticmethod
    def _rotate(directory: Path, profile: str, keep_files: int) -> None:
        paths = sorted(directory.glob(_log_pattern(profile)), reverse=True)
        for stale in paths[keep_files:]:
            stale.unlink(missing_ok=True)

    def emit(
        self,
        *,
        tool: str,
        arguments: Mapping[str, Any],
        agent: str,
        duration_seconds: float,
        result: types.CallToolResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        response: dict[str, Any]
        if result is not None:
            response = {"result": result.model_dump(mode="json", exclude_none=True)}
        elif error is not None:
            response = {
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                }
            }
        else:
            raise ValueError("result or error is required")
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "duration_ms": round(duration_seconds * 1000, 3),
            "agent": agent,
            "request": {
                "method": "tools/call",
                "params": {"name": tool, "arguments": dict(arguments)},
            },
            "response": response,
        }
        payload = (
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND)
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)


def latest_log(
    profile: str, *, directory: str | Path | None = None
) -> Path:
    directory = log_directory(profile, directory)
    paths = tuple(directory.glob(_log_pattern(profile)))
    if not paths:
        raise FileNotFoundError(f"no MCP log files for profile '{profile}'")
    return max(paths, key=lambda path: path.name)


def iter_log(path: str | Path, *, follow: bool = False) -> Generator[str, None, None]:
    """Yield the current log and optionally wait for appended lines."""

    with Path(path).open(encoding="utf-8") as stream:
        while True:
            line = stream.readline()
            if line:
                yield line
            elif not follow:
                return
            else:
                time.sleep(0.1)

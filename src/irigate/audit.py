from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import TextIO


class AuditLog:
    """Emit one metadata-only JSON line for a completed or rejected call."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def emit(
        self,
        *,
        upstream: str | None,
        tool: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "upstream": upstream,
            "tool": tool,
            "outcome": outcome,
            "duration_ms": round(duration_seconds * 1000, 3),
        }
        print(
            json.dumps(record, sort_keys=True, separators=(",", ":")),
            file=self._stream or sys.stderr,
            flush=True,
        )

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from irigate.models import BrokerConfig
from irigate.qualification import QualificationResult


@dataclass(slots=True)
class _Duration:
    count: int = 0
    total_ms: float = 0.0

    def add(self, seconds: float) -> None:
        self.count += 1
        self.total_ms += seconds * 1000

    def snapshot(self) -> dict[str, int | float]:
        return {"count": self.count, "total_ms": round(self.total_ms, 3)}


@dataclass(slots=True)
class _UpstreamMetrics:
    requested_mode: str
    qualifier: str | None
    qualification: str = "not_requested"
    effective_mode: str = "isolated"
    logical_bindings: set[object] = field(default_factory=set)
    live_instances: int = 0
    spawns: int = 0
    reuse_hits: int = 0
    startup_duration: _Duration = field(default_factory=_Duration)
    queue_duration: _Duration = field(default_factory=_Duration)
    call_duration: _Duration = field(default_factory=_Duration)
    failures: int = 0
    crashes: int = 0


class RuntimeMetrics:
    """Metadata-only runtime counters and atomic JSON snapshots."""

    def __init__(self, config: BrokerConfig) -> None:
        self.config = config
        self._upstreams = {
            key: _UpstreamMetrics(
                requested_mode="shared" if value.shareable else "isolated",
                qualifier=value.qualifier,
            )
            for key, value in config.upstreams.items()
        }

    def qualification(self, key: str, result: QualificationResult) -> None:
        item = self._upstreams[key]
        item.qualification = "qualified" if result.admitted else "rejected"
        item.effective_mode = "shared" if result.admitted else "isolated"

    def reconfigure(self, config: BrokerConfig) -> None:
        """Adopt a reloaded profile while retaining process and call counters."""

        for key, value in config.upstreams.items():
            self.ensure_upstream(key, value.shareable, value.qualifier)
            item = self._upstreams[key]
            item.requested_mode = "shared" if value.shareable else "isolated"
            item.qualifier = value.qualifier
        self.config = config

    def ensure_upstream(self, key: str, shareable: bool, qualifier: str | None) -> None:
        if key not in self._upstreams:
            self._upstreams[key] = _UpstreamMetrics(
                requested_mode="shared" if shareable else "isolated",
                qualifier=qualifier,
            )

    def effective_mode(self, key: str, mode: str) -> None:
        self._upstreams[key].effective_mode = mode

    def binding(self, key: str, session: object) -> None:
        self._upstreams[key].logical_bindings.add(session)

    def spawned(self, key: str, seconds: float) -> None:
        item = self._upstreams[key]
        item.spawns += 1
        item.live_instances += 1
        item.startup_duration.add(seconds)

    def closed(self, key: str) -> None:
        item = self._upstreams[key]
        item.live_instances = max(0, item.live_instances - 1)

    def reused(self, key: str) -> None:
        self._upstreams[key].reuse_hits += 1

    def duration(self, key: str, kind: str, seconds: float) -> None:
        getattr(self._upstreams[key], kind).add(seconds)

    def failed(self, key: str, *, crash: bool = False) -> None:
        item = self._upstreams[key]
        item.failures += 1
        if crash:
            item.crashes += 1

    def snapshot(self) -> dict[str, Any]:
        upstreams: dict[str, Any] = {}
        avoided = 0
        has_shared_evidence = False
        for key in self.config.upstreams:
            item = self._upstreams[key]
            clients = len(item.logical_bindings)
            if item.effective_mode == "shared" and clients >= 2:
                avoided += clients - 1
                has_shared_evidence = True
            upstreams[key] = {
                "requested_mode": item.requested_mode,
                "qualifier": item.qualifier,
                "qualification": item.qualification,
                "effective_mode": item.effective_mode,
                "logical_bindings": clients,
                "live_instances": item.live_instances,
                "spawns": item.spawns,
                "reuse_hits": item.reuse_hits,
                "startup_duration": item.startup_duration.snapshot(),
                "queue_duration": item.queue_duration.snapshot(),
                "call_duration": item.call_duration.snapshot(),
                "failures": item.failures,
                "crashes": item.crashes,
            }
        if has_shared_evidence:
            evidence = "qualified"
        elif any(item.requested_mode == "shared" for item in self._upstreams.values()):
            evidence = "insufficient_evidence"
        else:
            evidence = "isolated"
        return {
            "schema_version": 1,
            "profile": self.config.name,
            "upstreams": upstreams,
            "summary": {"evidence": evidence, "avoided_instances": avoided},
        }

    def write(self) -> None:
        path = self.config.runtime_report_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(self.snapshot(), sort_keys=True, indent=2) + "\n")
        os.replace(temporary, path)

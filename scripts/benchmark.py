from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from irigate.app import create_app
from irigate.config import load_config
from irigate.models import BrokerConfig
from irigate.upstream import UpstreamWorker

ROOT = Path(__file__).resolve().parents[1]
TOOL = "resolve-library-id"
ARGUMENTS = {
    "libraryName": "Python",
    "query": "benchmark Python documentation lookup",
}


def upstream_processes() -> set[int]:
    matches: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                errors="replace"
            )
        except (FileNotFoundError, PermissionError):
            continue
        if "context7-mcp" in command and "scripts/benchmark.py" not in command:
            matches.add(int(entry.name))
    return matches


def upstream_instance_roots(processes: set[int]) -> set[int]:
    roots: set[int] = set()
    for process in processes:
        try:
            parent_line = next(
                line
                for line in (Path("/proc") / str(process) / "status")
                .read_text()
                .splitlines()
                if line.startswith("PPid:")
            )
            parent = int(parent_line.split()[1])
        except (FileNotFoundError, PermissionError, StopIteration, ValueError, IndexError):
            continue
        if parent not in processes:
            roots.add(process)
    return roots


def rss_bytes(processes: set[int]) -> int:
    page_size = os.sysconf("SC_PAGE_SIZE")
    total = 0
    for process in processes:
        try:
            resident_pages = int(
                (Path("/proc") / str(process) / "statm").read_text().split()[1]
            )
        except (FileNotFoundError, PermissionError, ValueError, IndexError):
            continue
        total += resident_pages * page_size
    return total


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def wait_for_children_to_exit(baseline: set[int], timeout: float = 10.0) -> set[int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = upstream_processes() - baseline
        if not remaining:
            return set()
        await asyncio.sleep(0.05)
    return upstream_processes() - baseline


def latency_summary(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(values) * 1000, 3),
        "min_ms": round(min(values) * 1000, 3),
        "max_ms": round(max(values) * 1000, 3),
    }


def call_failed(result: Any) -> bool:
    if result.isError:
        return True
    text = " ".join(
        str(getattr(content, "text", "")) for content in result.content
    ).lower()
    return "rate limit" in text or "try again in" in text


async def direct_trial(config: BrokerConfig, clients: int) -> dict[str, Any]:
    baseline = upstream_processes()
    upstream = config.upstreams["context7"]
    environment = config.resolve_environment()["context7"]
    workers = [UpstreamWorker(f"direct-{index}", upstream, environment) for index in range(clients)]
    started = time.monotonic()

    async def start(worker: UpstreamWorker) -> float:
        await worker.start()
        return time.monotonic() - started

    startup_latencies = await asyncio.gather(*(start(worker) for worker in workers))
    processes = upstream_processes() - baseline
    instances = upstream_instance_roots(processes)
    measured_rss = rss_bytes(processes)
    first_latencies: list[float] = []
    steady_latencies: list[float] = []
    errors = 0

    async def call(worker: UpstreamWorker, target: list[float]) -> None:
        nonlocal errors
        call_started = time.monotonic()
        result = await worker.call_tool(TOOL, ARGUMENTS)
        target.append(time.monotonic() - call_started)
        errors += int(call_failed(result))

    await asyncio.gather(*(call(worker, first_latencies) for worker in workers))
    await asyncio.gather(*(call(worker, steady_latencies) for worker in workers))
    await asyncio.gather(*(worker.close() for worker in workers))
    orphans = await wait_for_children_to_exit(baseline)
    if len(instances) != clients:
        raise RuntimeError(
            f"direct process accounting found {len(instances)} instances for {clients} clients"
        )
    if orphans:
        raise RuntimeError(f"direct orphan_processes={sorted(orphans)}")
    return {
        "mode": "direct",
        "clients": clients,
        "upstream_instances": len(instances),
        "process_tree_count": len(processes),
        "resident_memory_bytes": measured_rss,
        "startup_to_first_list": latency_summary(startup_latencies),
        "first_call": latency_summary(first_latencies),
        "steady_call": latency_summary(steady_latencies),
        "calls": clients * 2,
        "errors": errors,
        "error_rate": errors / (clients * 2),
        "call_latency_valid": errors == 0,
        "orphans_after_shutdown": len(orphans),
    }


async def broker_trial(config: BrokerConfig, clients: int, report_path: Path) -> dict[str, Any]:
    baseline = upstream_processes()
    port = free_port()
    benchmark_config = config.model_copy(
        update={
            "port": port,
            "runtime_report_path": report_path,
            "upstreams": {"context7": config.upstreams["context7"]},
        }
    )
    report_path.unlink(missing_ok=True)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(benchmark_config, require_qualified_sharing=True),
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="on",
        )
    )
    server_started = time.monotonic()
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        if server_task.done():
            await server_task
            raise RuntimeError("benchmark broker exited before startup")
        await asyncio.sleep(0.01)
    url = f"http://127.0.0.1:{port}/mcp?tools=context7__{TOOL}"
    release = asyncio.Event()
    ready = asyncio.Condition()
    ready_count = 0
    startup_latencies: list[float] = []
    first_latencies: list[float] = []
    steady_latencies: list[float] = []
    errors = 0

    async def client() -> None:
        nonlocal errors, ready_count
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                await session.list_tools()
                startup_latencies.append(time.monotonic() - server_started)
                call_started = time.monotonic()
                first = await session.call_tool(f"context7__{TOOL}", ARGUMENTS)
                first_latencies.append(time.monotonic() - call_started)
                errors += int(call_failed(first))
                call_started = time.monotonic()
                steady = await session.call_tool(f"context7__{TOOL}", ARGUMENTS)
                steady_latencies.append(time.monotonic() - call_started)
                errors += int(call_failed(steady))
                async with ready:
                    ready_count += 1
                    ready.notify_all()
                await release.wait()

    tasks = [asyncio.create_task(client()) for _ in range(clients)]
    async with ready:
        await ready.wait_for(lambda: ready_count == clients)
    processes = upstream_processes() - baseline
    instances = upstream_instance_roots(processes)
    measured_rss = rss_bytes(processes)
    runtime_report = json.loads(report_path.read_text(encoding="utf-8"))
    context7 = runtime_report["upstreams"]["context7"]
    release.set()
    await asyncio.gather(*tasks)
    server.should_exit = True
    await server_task
    orphans = await wait_for_children_to_exit(baseline)
    external_instances = len(instances)
    runtime_live = int(context7["live_instances"])
    effective_mode = str(context7["effective_mode"])
    expected_avoided = max(0, clients - 1) if effective_mode == "shared" else 0
    reconciled = (
        runtime_live == external_instances
        and int(context7["logical_bindings"]) == clients
        and int(runtime_report["summary"]["avoided_instances"]) == expected_avoided
    )
    if effective_mode == "shared":
        reconciled = reconciled and runtime_live == 1
    elif effective_mode != "degraded":
        reconciled = False
    if not reconciled:
        raise RuntimeError("external process count disagrees with runtime report")
    if orphans:
        raise RuntimeError(f"broker orphan_processes={sorted(orphans)}")
    return {
        "mode": "broker",
        "clients": clients,
        "upstream_instances": external_instances,
        "process_tree_count": len(processes),
        "resident_memory_bytes": measured_rss,
        "startup_to_first_list": latency_summary(startup_latencies),
        "first_call": latency_summary(first_latencies),
        "steady_call": latency_summary(steady_latencies),
        "calls": clients * 2,
        "errors": errors,
        "error_rate": errors / (clients * 2),
        "call_latency_valid": errors == 0,
        "orphans_after_shutdown": len(orphans),
        "runtime_report": {
            "effective_mode": effective_mode,
            "logical_bindings": context7["logical_bindings"],
            "live_instances": runtime_live,
            "spawns": context7["spawns"],
            "reuse_hits": context7["reuse_hits"],
            "avoided_instances": runtime_report["summary"]["avoided_instances"],
            "evidence": runtime_report["summary"]["evidence"],
        },
        "process_report_reconciled": reconciled,
    }


def aggregate(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for trial in trials:
        groups.setdefault((trial["mode"], trial["clients"]), []).append(trial)
    summaries: list[dict[str, Any]] = []
    for (mode, clients), rows in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        summary: dict[str, Any] = {"mode": mode, "clients": clients, "repetitions": len(rows)}
        summary["valid_call_latency_repetitions"] = sum(
            int(bool(row["call_latency_valid"])) for row in rows
        )
        for field in ("upstream_instances", "process_tree_count", "resident_memory_bytes", "error_rate", "orphans_after_shutdown"):
            values = [float(row[field]) for row in rows]
            summary[field] = {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
        for field in ("startup_to_first_list", "first_call", "steady_call"):
            values = [float(row[field]["median_ms"]) for row in rows]
            summary[f"{field}_median_ms"] = {
                "median": round(statistics.median(values), 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
            }
        summaries.append(summary)
    return summaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "profiles" / "benchmark-heavy.yaml")
    parser.add_argument("--clients", nargs="+", default=["1,5,20"])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / ".irigate" / "benchmark-results.json")
    return parser.parse_args()


async def run() -> dict[str, Any]:
    args = parse_args()
    client_counts = [
        int(value)
        for argument in args.clients
        for value in argument.split(",")
        if value
    ]
    if not client_counts or any(value < 1 for value in client_counts):
        raise ValueError("--clients requires positive comma- or space-separated integers")
    config = load_config(args.config)
    if "context7" not in config.upstreams or not config.upstreams["context7"].shareable:
        raise RuntimeError("benchmark requires the qualified shared Context7 upstream")
    trials: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="irigate-benchmark-") as directory:
        report_path = Path(directory) / "runtime-report.json"
        for clients in client_counts:
            for repetition in range(args.repetitions):
                print(f"benchmark direct clients={clients} repetition={repetition + 1}", flush=True)
                trials.append(await direct_trial(config, clients))
                print(f"benchmark broker clients={clients} repetition={repetition + 1}", flush=True)
                trials.append(await broker_trial(config, clients, report_path))
    payload = {
        "profile": str(args.config),
        "upstream": "context7",
        "context": {
            "kind": "identical",
            "credentials": "none",
            "workspace": "none",
            "scope_limit": "results do not apply to isolated or credential/workspace-bound upstreams",
        },
        "repetitions": args.repetitions,
        "raw_trials": trials,
        "summary": aggregate(trials),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    return payload


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

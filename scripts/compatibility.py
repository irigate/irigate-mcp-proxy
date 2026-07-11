from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from irigate.config import load_config

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/mcp?tools=context7__resolve-library-id"
REPORT = ROOT / ".irigate" / "runtime-report.json"
ACTIVE_HERMES_HOME = Path.home() / ".hermes" / "profiles" / "hermes-vc"
ACTIVE_CODEX_HOME = Path.home() / ".codex"


def wait_ready(process: subprocess.Popen[str], timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"broker exited early ({process.returncode})\n{stdout}\n{stderr}"
            )
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex((HOST, PORT)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError("compatibility broker did not become ready")


def call_count() -> int:
    if not REPORT.exists():
        return 0
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    return int(
        report["upstreams"]["context7"]["call_duration"]["count"]
    )


def run_client(
    name: str,
    command: list[str],
    environment: dict[str, str],
    marker: str,
) -> dict[str, Any]:
    before = call_count()
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    duration = time.monotonic() - started
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        raise RuntimeError(f"{name} exited {completed.returncode}")
    if marker not in output:
        raise RuntimeError(f"{name} omitted its result marker")
    after = call_count()
    if after != before + 1:
        raise RuntimeError(f"{name} broker call delta was {after - before}, expected 1")
    return {
        "client": name,
        "status": "validated",
        "broker_calls": 1,
        "duration_seconds": round(duration, 3),
    }


def configure_codex(home: Path) -> dict[str, str]:
    auth = ACTIVE_CODEX_HOME / "auth.json"
    if not auth.exists():
        raise RuntimeError("Codex authentication is unavailable")
    (home / "auth.json").symlink_to(auth)
    (home / "config.toml").write_text(
        f'''[mcp_servers.irigate]\nurl = "{URL}"\nenabled = true\ndefault_tools_approval_mode = "approve"\nstartup_timeout_sec = 30\ntool_timeout_sec = 60\n''',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(home)
    return environment


def configure_kilo(config_home: Path) -> dict[str, str]:
    kilo_config = config_home / "kilo"
    kilo_config.mkdir(parents=True)
    (kilo_config / "kilo.json").write_text(
        f'''{{\n  "mcp": {{\n    "irigate": {{\n      "type": "remote",\n      "url": "{URL}",\n      "enabled": true,\n      "oauth": false,\n      "timeout": 60000\n    }}\n  }},\n  "permission": "allow"\n}}\n''',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["XDG_CONFIG_HOME"] = str(config_home)
    return environment


def configure_hermes(home: Path) -> dict[str, str]:
    auth = ACTIVE_HERMES_HOME / "auth.json"
    if not auth.exists():
        raise RuntimeError("Hermes OpenAI Codex authentication is unavailable")
    (home / "auth.json").symlink_to(auth)
    (home / "config.yaml").write_text(
        f'''model:\n  default: gpt-5.6-sol\n  provider: openai-codex\nmcp_servers:\n  irigate:\n    url: "{URL}"\n    tools:\n      include:\n        - context7__resolve-library-id\n''',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["HERMES_HOME"] = str(home)
    return environment


def claude_status() -> dict[str, Any]:
    if shutil.which("claude") is None:
        return {"client": "Claude Code", "status": "unavailable", "reason": "not installed"}
    authenticated = subprocess.run(
        ["claude", "auth", "status"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    if authenticated.returncode != 0:
        return {
            "client": "Claude Code",
            "status": "unavailable",
            "reason": "not authenticated",
        }
    return {
        "client": "Claude Code",
        "status": "unsupported",
        "reason": "authenticated CLI probe not implemented",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "profiles" / "mvp.yaml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".irigate" / "compatibility-results.json",
    )
    return parser.parse_args()


def main() -> int:
    global HOST, PORT, URL, REPORT
    args = parse_args()
    config = load_config(args.config)
    HOST = config.host
    PORT = config.port
    URL = f"http://{HOST}:{PORT}/mcp?tools=context7__resolve-library-id"
    REPORT = config.runtime_report_path
    if not REPORT.is_absolute():
        REPORT = ROOT / REPORT
    REPORT.unlink(missing_ok=True)
    broker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "irigate",
            "--config",
            str(args.config),
            "--require-qualified-sharing",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    temp_root = Path(tempfile.mkdtemp(prefix="irigate-clients-"))
    results: list[dict[str, Any]] = []
    shutdown_output = ("", "")
    try:
        wait_ready(broker)
        kilo_environment = configure_kilo(temp_root / "config")
        results.append(
            run_client(
                "Kilo/OpenCode",
                [
                    "opencode",
                    "run",
                    "--model",
                    "kilo/kilo-auto/free",
                    "--agent",
                    "ask",
                    "--format",
                    "json",
                    "--auto",
                    "--dir",
                    str(ROOT),
                    "Call context7__resolve-library-id exactly once with libraryName='Kilo' and query='Kilo MCP compatibility'. Return KILO_STREAMABLE_OK and stop.",
                ],
                kilo_environment,
                "KILO_STREAMABLE_OK",
            )
        )

        hermes_home = temp_root / "hermes"
        hermes_home.mkdir()
        results.append(
            run_client(
                "Hermes",
                [
                    "hermes",
                    "--oneshot",
                    "Call context7__resolve-library-id exactly once with libraryName='Hermes' and query='Hermes MCP compatibility'. Return HERMES_STREAMABLE_OK and stop.",
                    "--ignore-rules",
                    "--provider",
                    "openai-codex",
                    "--model",
                    "gpt-5.6-sol",
                ],
                configure_hermes(hermes_home),
                "HERMES_STREAMABLE_OK",
            )
        )

        codex_home = temp_root / "codex"
        codex_home.mkdir()
        results.append(
            run_client(
                "Codex",
                [
                    "codex",
                    "--ask-for-approval",
                    "never",
                    "exec",
                    "--ephemeral",
                    "--ignore-rules",
                    "--sandbox",
                    "read-only",
                    "-C",
                    str(ROOT),
                    "You must invoke the irigate MCP tool context7__resolve-library-id exactly once with libraryName='Codex' and query='Codex MCP compatibility'. Do not answer from memory and do not merely repeat this instruction: an external verifier checks the broker call count. Only after receiving the tool result, return CODEX_STREAMABLE_OK and stop.",
                ],
                configure_codex(codex_home),
                "CODEX_STREAMABLE_OK",
            )
        )
        results.append(claude_status())
    finally:
        if broker.poll() is None:
            broker.send_signal(signal.SIGTERM)
        try:
            shutdown_output = broker.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            broker.kill()
            shutdown_output = broker.communicate(timeout=5)
            raise RuntimeError("compatibility broker required SIGKILL")
        shutil.rmtree(temp_root, ignore_errors=True)

    if broker.returncode not in (0, -signal.SIGTERM):
        raise RuntimeError(f"broker shutdown exit was {broker.returncode}")
    if "Application shutdown complete" not in shutdown_output[1]:
        raise RuntimeError("broker did not report graceful shutdown")

    payload = {
        "transport": "Streamable HTTP",
        "endpoint": URL,
        "results": results,
        "graceful_shutdown": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

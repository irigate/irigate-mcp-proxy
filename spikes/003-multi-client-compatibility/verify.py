from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BROKER_DIR = ROOT / "spikes" / "001-streamable-http-roundtrip"
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/mcp"
ACTIVE_HERMES_HOME = Path.home() / ".hermes" / "profiles" / "hermes-vc"
ACTIVE_CODEX_HOME = Path.home() / ".codex"


def wait_ready(process: subprocess.Popen[str], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"broker exited early ({process.returncode})\n{stdout}\n{stderr}")
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex((HOST, PORT)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError("compatibility broker did not become ready")


def call_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def run_client(name: str, command: list[str], env: dict[str, str], marker: str, call_log: Path) -> str:
    before = call_count(call_log)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0, f"{name} exit={completed.returncode}\n{output}"
    assert marker in output, f"{name} omitted marker {marker}\n{output}"
    after = call_count(call_log)
    assert after == before + 1, f"{name} broker calls: before={before}, after={after}\n{output}"
    return output


def configure_codex(home: Path) -> dict[str, str]:
    auth = ACTIVE_CODEX_HOME / "auth.json"
    assert auth.exists(), "Codex authentication is unavailable"
    (home / "auth.json").symlink_to(auth)
    (home / "config.toml").write_text(
        f'''[mcp_servers.irigate]\nurl = "{URL}"\nenabled = true\ndefault_tools_approval_mode = "approve"\nstartup_timeout_sec = 15\ntool_timeout_sec = 15\n''',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    return env


def configure_kilo(config_home: Path) -> dict[str, str]:
    kilo_config = config_home / "kilo"
    kilo_config.mkdir(parents=True)
    (kilo_config / "kilo.json").write_text(
        f'''{{\n  "mcp": {{\n    "irigate": {{\n      "type": "remote",\n      "url": "{URL}",\n      "enabled": true,\n      "oauth": false,\n      "timeout": 15000\n    }}\n  }},\n  "permission": "allow"\n}}\n''',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(config_home)
    return env


def configure_hermes(home: Path) -> dict[str, str]:
    auth = ACTIVE_HERMES_HOME / "auth.json"
    assert auth.exists(), "Hermes OpenAI Codex authentication is unavailable"
    (home / "auth.json").symlink_to(auth)
    (home / "config.yaml").write_text(
        f'''model:\n  default: gpt-5.6-sol\n  provider: openai-codex\nmcp_servers:\n  irigate:\n    url: "{URL}"\n    tools:\n      include:\n        - echo__repeat\n''',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    return env


def main() -> None:
    call_log = HERE / "calls.log"
    call_log.unlink(missing_ok=True)
    broker_env = os.environ.copy()
    broker_env.update({"SPIKE_CALL_LOG": str(call_log), "SPIKE_PYTHON": sys.executable})
    broker = subprocess.Popen(
        [sys.executable, str(BROKER_DIR / "broker.py")],
        cwd=BROKER_DIR,
        env=broker_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    temp_root = Path(tempfile.mkdtemp(prefix="irigate-clients-"))
    try:
        wait_ready(broker)

        kilo_env = configure_kilo(temp_root / "config")
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
                "Call the irigate MCP tool echo__repeat exactly once with value KILO_STREAMABLE_OK. Return only the tool result.",
            ],
            kilo_env,
            "KILO_STREAMABLE_OK",
            call_log,
        )

        hermes_home = temp_root / "hermes"
        hermes_home.mkdir()
        hermes_env = configure_hermes(hermes_home)
        run_client(
            "Hermes",
            [
                "hermes",
                "--oneshot",
                "Call the irigate MCP tool echo__repeat exactly once with value HERMES_STREAMABLE_OK. Return only the tool result.",
                "--ignore-rules",
                "--provider",
                "openai-codex",
                "--model",
                "gpt-5.6-sol",
            ],
            hermes_env,
            "HERMES_STREAMABLE_OK",
            call_log,
        )

        codex_home = temp_root / "codex"
        codex_home.mkdir()
        codex_env = configure_codex(codex_home)
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
                "Call the irigate MCP tool echo__repeat exactly once with value CODEX_STREAMABLE_OK. Return only the tool result.",
            ],
            codex_env,
            "CODEX_STREAMABLE_OK",
            call_log,
        )
    finally:
        broker.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = broker.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            broker.kill()
            stdout, stderr = broker.communicate(timeout=5)
            raise AssertionError("compatibility broker required SIGKILL")
        shutil.rmtree(temp_root, ignore_errors=True)
        call_log.unlink(missing_ok=True)

    assert broker.returncode in (0, -signal.SIGTERM), (
        f"broker shutdown={broker.returncode}\n{stdout}\n{stderr}"
    )
    assert "Application shutdown complete" in stderr, stderr
    print(
        "VALIDATED: Hermes, Kilo/OpenCode, and Codex called Streamable HTTP directly; "
        "Claude unavailable (not authenticated)"
    )


if __name__ == "__main__":
    main()

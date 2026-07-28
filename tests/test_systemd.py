from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

from irigate.__main__ import build_parser
from irigate.models import BrokerConfig
from irigate.systemd import (
    SystemdPaths,
    reload_systemd_service,
    setup_systemd_service,
    sync_systemd_service,
)


def config() -> BrokerConfig:
    return BrokerConfig.model_validate(
        {
            "name": "systemd-test",
            "upstreams": {
                "echo": {
                    "command": "echo-server",
                    "env": {
                        "API_TOKEN": "${API_TOKEN}",
                        "LOG_LEVEL": "info",
                    },
                    "idle_timeout_seconds": 60,
                }
            },
        }
    )


class Runner:
    def __init__(self, *, active: bool = False) -> None:
        self.active = active
        self.calls: list[list[str]] = []

    def __call__(self, arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(arguments)
        is_active = arguments[2:4] == ["is-active", "--quiet"]
        return subprocess.CompletedProcess(
            arguments,
            0 if not is_active or self.active else 3,
        )


def paths(tmp_path: Path) -> SystemdPaths:
    return SystemdPaths(
        service=tmp_path / "home" / ".config" / "systemd" / "user" / "irigate.service",
        environment=tmp_path / "home" / ".config" / "irigate" / "irigate.env",
    )


def test_sync_writes_private_environment_and_restarts_active_service(tmp_path: Path) -> None:
    destination = paths(tmp_path)
    runner = Runner(active=True)
    profile = tmp_path / "profile.yaml"

    result = sync_systemd_service(
        config(),
        profile,
        python=Path(sys.executable),
        environ={"API_TOKEN": 'quote " and slash \\'},
        paths=destination,
        runner=runner,
    )

    assert result.paths == destination
    assert result.restarted is True
    assert destination.environment.read_text(encoding="utf-8") == 'API_TOKEN="quote \\" and slash \\\\"\n'
    assert stat.S_IMODE(destination.environment.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.environment.parent.stat().st_mode) == 0o700
    unit = destination.service.read_text(encoding="utf-8")
    assert "EnvironmentFile=%h/.config/irigate/irigate.env" in unit
    assert f'ExecStart="{Path(sys.executable).resolve()}" -m irigate --config "{profile.resolve()}"' in unit
    assert f'ExecReload="{Path(sys.executable).resolve()}" -m irigate reload --config "{profile.resolve()}"' in unit
    assert 'quote "' not in unit
    assert runner.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "is-active", "--quiet", "irigate.service"],
        ["systemctl", "--user", "restart", "irigate.service"],
    ]


def test_sync_leaves_an_inactive_service_stopped(tmp_path: Path) -> None:
    runner = Runner()

    result = sync_systemd_service(
        config(),
        tmp_path / "profile.yaml",
        python=Path(sys.executable),
        environ={"API_TOKEN": "synthetic"},
        paths=paths(tmp_path),
        runner=runner,
    )

    assert result.restarted is False
    assert runner.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "is-active", "--quiet", "irigate.service"],
    ]


def test_setup_starts_service_and_reload_uses_the_unit_action(tmp_path: Path) -> None:
    destination = paths(tmp_path)
    runner = Runner()

    result = setup_systemd_service(
        config(),
        tmp_path / "profile.yaml",
        python=Path(sys.executable),
        environ={"API_TOKEN": "synthetic"},
        paths=destination,
        runner=runner,
    )
    reload_systemd_service(runner)

    assert result == destination
    assert runner.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "irigate.service"],
        ["systemctl", "--user", "reload", "irigate.service"],
    ]


def test_systemd_cli_accepts_config_after_each_action() -> None:
    parser = build_parser()

    for action in ("setup", "sync", "reload"):
        parsed = parser.parse_args(["systemd", action, "--config", "profile.yaml"])
        assert parsed.config == "profile.yaml"
        assert parsed.systemd_command == action

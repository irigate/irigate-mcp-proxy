from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from irigate.models import BrokerConfig

_SERVICE_NAME = "irigate.service"
_SYSTEMCTL = ("systemctl", "--user")


class SystemdError(ValueError):
    """A safe-to-display systemd user-service error."""


@dataclass(frozen=True, slots=True)
class SystemdPaths:
    service: Path
    environment: Path


@dataclass(frozen=True, slots=True)
class SystemdSyncResult:
    paths: SystemdPaths
    restarted: bool


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def systemd_paths(home: Path | None = None) -> SystemdPaths:
    base = Path.home() if home is None else home
    return SystemdPaths(
        service=base / ".config" / "systemd" / "user" / _SERVICE_NAME,
        environment=base / ".config" / "irigate" / "irigate.env",
    )


def _systemd_quote(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise SystemdError("systemd service values must not contain line breaks or NUL bytes")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _environment_value(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise SystemdError("environment values must not contain line breaks or NUL bytes")
    return _systemd_quote(value)


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)
    os.chmod(path, mode)


def _environment_document(
    config: BrokerConfig, environ: Mapping[str, str] | None = None
) -> str:
    source = os.environ if environ is None else environ
    config.resolve_environment(source)
    return "".join(
        f"{name}={_environment_value(source[name])}\n"
        for name in sorted(config.environment_names)
    )


def _service_document(config_path: Path, python: Path) -> str:
    config = str(config_path.resolve())
    # A uv tool's interpreter symlink selects its virtual environment.
    # Resolving it runs Python outside that environment, where ``irigate`` is
    # not installed.
    command = _systemd_quote(str(python.absolute()))
    profile = _systemd_quote(config)
    return "\n".join(
        (
            "[Unit]",
            "Description=Irigate local MCP broker",
            "After=network.target",
            "",
            "[Service]",
            "Type=simple",
            "EnvironmentFile=%h/.config/irigate/irigate.env",
            f"ExecStart={command} -m irigate --config {profile}",
            f"ExecReload={command} -m irigate reload --config {profile}",
            "Restart=on-failure",
            "RestartSec=2",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        )
    )


def write_systemd_service(
    config: BrokerConfig,
    config_path: Path,
    *,
    python: Path,
    environ: Mapping[str, str] | None = None,
    paths: SystemdPaths | None = None,
) -> SystemdPaths:
    """Write the user unit and its private environment file without invoking systemd."""

    destination = systemd_paths() if paths is None else paths
    _atomic_write(destination.environment, _environment_document(config, environ), 0o600)
    _atomic_write(destination.service, _service_document(config_path, python), 0o644)
    return destination


def _systemctl(
    arguments: Sequence[str], runner: CommandRunner = subprocess.run
) -> subprocess.CompletedProcess[str]:
    completed = runner(
        [*_SYSTEMCTL, *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise SystemdError(f"systemctl {' '.join(arguments)} failed" + (f": {detail}" if detail else ""))
    return completed


def setup_systemd_service(
    config: BrokerConfig,
    config_path: Path,
    *,
    python: Path,
    environ: Mapping[str, str] | None = None,
    paths: SystemdPaths | None = None,
    runner: CommandRunner = subprocess.run,
) -> SystemdPaths:
    """Install, enable, and start the selected profile as irigate.service."""

    destination = write_systemd_service(
        config,
        config_path,
        python=python,
        environ=environ,
        paths=paths,
    )
    _systemctl(("daemon-reload",), runner)
    _systemctl(("enable", "--now", _SERVICE_NAME), runner)
    return destination


def sync_systemd_service(
    config: BrokerConfig,
    config_path: Path,
    *,
    python: Path,
    environ: Mapping[str, str] | None = None,
    paths: SystemdPaths | None = None,
    runner: CommandRunner = subprocess.run,
) -> SystemdSyncResult:
    """Mirror referenced environment values and restart an active user service."""

    destination = write_systemd_service(
        config,
        config_path,
        python=python,
        environ=environ,
        paths=paths,
    )
    _systemctl(("daemon-reload",), runner)
    active = runner(
        [*_SYSTEMCTL, "is-active", "--quiet", _SERVICE_NAME],
        text=True,
        capture_output=True,
        check=False,
    ).returncode == 0
    if active:
        _systemctl(("restart", _SERVICE_NAME), runner)
    return SystemdSyncResult(paths=destination, restarted=active)


def reload_systemd_service(runner: CommandRunner = subprocess.run) -> None:
    """Run the unit's connection-preserving Irigate reload action."""

    _systemctl(("reload", _SERVICE_NAME), runner)

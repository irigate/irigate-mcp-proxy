from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path

import pytest

from irigate import __version__
from irigate.__main__ import build_parser
from irigate.restart import (
    CONTROL_SCHEMA_VERSION,
    RestartControl,
    RestartError,
    control_path,
    process_is_irigate,
    read_control,
    reload_running,
    remove_control,
    stop_running,
    write_control,
)


def test_control_path_is_adjacent_to_runtime_report(tmp_path: Path) -> None:
    assert control_path(tmp_path / "runtime.json") == tmp_path / "runtime.json.control"


def test_control_path_requires_runtime_report() -> None:
    with pytest.raises(RestartError, match="runtime_report_path"):
        control_path(None)


def control(tmp_path: Path) -> RestartControl:
    return RestartControl(
        schema_version=CONTROL_SCHEMA_VERSION,
        profile="test",
        config_path=str((tmp_path / "profile.yaml").resolve()),
        pid=os.getpid(),
        instance_id="instance-1",
        version="0.1.0",
    )


def test_control_round_trip_is_atomic_and_strict(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json.control"
    expected = control(tmp_path)

    write_control(path, expected)

    assert read_control(
        path,
        expected_profile=expected.profile,
        expected_config_path=Path(expected.config_path),
    ) == expected
    assert not path.with_name(path.name + ".tmp").exists()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(schema_version=99), "schema_version"),
        (lambda value: value.pop("pid"), "fields"),
        (lambda value: value.update(pid=0), "pid"),
        (lambda value: value.update(instance_id=""), "instance_id"),
        (lambda value: value.update(extra="value"), "fields"),
    ],
)
def test_read_control_rejects_invalid_documents(tmp_path: Path, mutate, message: str) -> None:
    path = tmp_path / "runtime.json.control"
    value = control(tmp_path).to_dict()
    mutate(value)
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(RestartError, match=message):
        read_control(path)


def test_read_control_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json.control"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(RestartError, match="invalid process control document"):
        read_control(path)


def test_read_control_rejects_stale_profile_and_config(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json.control"
    expected = control(tmp_path)
    write_control(path, expected)

    with pytest.raises(RestartError, match="profile does not match"):
        read_control(path, expected_profile="other")
    with pytest.raises(RestartError, match="configuration path does not match"):
        read_control(path, expected_config_path=tmp_path / "other.yaml")


def test_remove_control_only_removes_owned_instance(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json.control"
    expected = control(tmp_path)
    write_control(path, expected)

    assert remove_control(path, "other") is False
    assert path.exists()
    assert remove_control(path, expected.instance_id) is True
    assert not path.exists()


def test_process_identity_accepts_irigate_python_and_console_forms(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    (proc / "1").mkdir(parents=True)
    (proc / "1" / "cmdline").write_bytes(b"/usr/bin/python3\0-m\0irigate\0")
    (proc / "2").mkdir()
    (proc / "2" / "cmdline").write_bytes(b"/venv/bin/irigate\0--config\0x\0")
    (proc / "3").mkdir()
    (proc / "3" / "cmdline").write_bytes(b"/usr/bin/python3\0worker.py\0")

    assert process_is_irigate(1, proc_root=proc)
    assert process_is_irigate(2, proc_root=proc)
    assert not process_is_irigate(3, proc_root=proc)
    assert not process_is_irigate(4, proc_root=proc)


@pytest.mark.parametrize("command", ["reload", "stop"])
def test_process_control_subcommands_accept_config_before_or_after_command(
    command: str,
) -> None:
    parser = build_parser()

    assert parser.parse_args(["--config", "one.yaml", command]).config == "one.yaml"
    assert parser.parse_args([command, "--config", "two.yaml"]).config == "two.yaml"


def test_cli_help_lists_process_control_commands_and_version(capsys) -> None:
    parser = build_parser()
    assert version("irigate") == __version__

    with pytest.raises(SystemExit) as root_exit:
        parser.parse_args(["--help"])
    assert root_exit.value.code == 0
    root_help = capsys.readouterr().out
    assert f"Irigate {__version__}" in root_help
    assert "~/.config/irigate/config.yaml" in root_help
    assert "reload" in root_help
    assert "stop" in root_help

    for command in ("tools", "reload", "stop"):
        with pytest.raises(SystemExit) as command_exit:
            parser.parse_args([command, "--help"])
        assert command_exit.value.code == 0
        command_help = capsys.readouterr().out
        assert "~/.config/irigate/config.yaml" in command_help
        if command in {"reload", "stop"}:
            assert f"Irigate {__version__}" in command_help

    with pytest.raises(SystemExit) as version_exit:
        parser.parse_args(["--version"])
    assert version_exit.value.code == 0
    assert capsys.readouterr().out == f"irigate {__version__}\n"


def test_reload_running_signals_only_the_verified_instance(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json.control"
    expected = control(tmp_path)
    write_control(path, expected)
    signals: list[tuple[int, int]] = []

    result = reload_running(
        path,
        expected_profile=expected.profile,
        expected_config_path=Path(expected.config_path),
        process_check=lambda pid: pid == expected.pid,
        kill=lambda pid, requested_signal: signals.append((pid, requested_signal)),
    )

    assert result == expected
    assert signals == [(expected.pid, signal.SIGHUP)]
    assert path.exists()


def test_stop_running_signals_only_the_verified_instance(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json.control"
    expected = control(tmp_path)
    write_control(path, expected)
    signals: list[tuple[int, int]] = []

    def kill(pid: int, requested_signal: int) -> None:
        signals.append((pid, requested_signal))
        path.unlink()

    result = stop_running(
        path,
        expected_profile=expected.profile,
        expected_config_path=Path(expected.config_path),
        process_check=lambda pid: pid == expected.pid,
        kill=kill,
        timeout_seconds=0.1,
        poll_interval_seconds=0.001,
    )

    assert result == expected
    assert signals == [(expected.pid, signal.SIGTERM)]


def test_stop_running_rejects_a_stale_process_without_signaling(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json.control"
    expected = control(tmp_path)
    write_control(path, expected)
    signals: list[tuple[int, int]] = []

    with pytest.raises(RestartError, match="not a running Irigate instance"):
        stop_running(
            path,
            expected_profile=expected.profile,
            expected_config_path=Path(expected.config_path),
            process_check=lambda _pid: False,
            kill=lambda pid, requested_signal: signals.append((pid, requested_signal)),
        )

    assert signals == []


def test_stop_running_requires_owned_control_cleanup(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json.control"
    expected = control(tmp_path)
    write_control(path, expected)

    with pytest.raises(RestartError, match="shutdown was not observed"):
        stop_running(
            path,
            expected_profile=expected.profile,
            expected_config_path=Path(expected.config_path),
            process_check=lambda _pid: True,
            kill=lambda _pid, _requested_signal: None,
            timeout_seconds=0,
        )

    assert path.exists()


def write_stop_profile(tmp_path: Path, port: int) -> tuple[Path, Path]:
    report_path = tmp_path / "runtime.json"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "name: stop-test",
                "host: 127.0.0.1",
                f"port: {port}",
                f"runtime_report_path: {report_path}",
                "upstreams:",
                "  dormant:",
                "    transport: stdio",
                "    command: dormant-command-is-not-started",
                "    args: []",
                "    env: {}",
                "    shareable: false",
                "    concurrency: serial",
                "    call_timeout_seconds: 5",
                "    idle_timeout_seconds: 60",
            ]
        ),
        encoding="utf-8",
    )
    return profile_path, report_path


def test_cli_stop_gracefully_stops_a_running_irigate_instance(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    profile_path, report_path = write_stop_profile(tmp_path, port)
    path = control_path(report_path)
    server = subprocess.Popen(
        [sys.executable, "-m", "irigate", "--config", str(profile_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(300):
            if path.exists():
                break
            if server.poll() is not None:
                break
            time.sleep(0.01)
        assert path.exists(), server.stderr.read() if server.stderr is not None else ""

        result = subprocess.run(
            [sys.executable, "-m", "irigate", "stop", "--config", str(profile_path)],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == "Irigate stopped\n"
        assert server.wait(timeout=5) == -signal.SIGTERM
        assert not path.exists()
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=5)


def test_cli_reload_keeps_the_running_irigate_instance_available(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    profile_path, report_path = write_stop_profile(tmp_path, port)
    path = control_path(report_path)
    server = subprocess.Popen(
        [sys.executable, "-m", "irigate", "--config", str(profile_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(300):
            if path.exists():
                break
            if server.poll() is not None:
                break
            time.sleep(0.01)
        assert path.exists(), server.stderr.read() if server.stderr is not None else ""

        result = subprocess.run(
            [sys.executable, "-m", "irigate", "reload", "--config", str(profile_path)],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == "Irigate reload requested\n"
        time.sleep(0.2)
        assert server.poll() is None
        assert path.exists()
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=5)

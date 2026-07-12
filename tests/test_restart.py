from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from irigate.restart import (
    CONTROL_SCHEMA_VERSION,
    RestartControl,
    RestartError,
    control_path,
    process_is_irigate,
    read_control,
    remove_control,
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

    with pytest.raises(RestartError, match="invalid restart control document"):
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

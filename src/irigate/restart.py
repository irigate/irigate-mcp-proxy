from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

CONTROL_SCHEMA_VERSION = 2
_CONTROL_FIELDS_V1 = {
    "schema_version",
    "profile",
    "config_path",
    "pid",
    "instance_id",
    "version",
}
_CONTROL_FIELDS_V2 = _CONTROL_FIELDS_V1 | {
    "host",
    "port",
    "runtime_report_path",
    "runtime_log_file",
    "started_at",
}


class RestartError(ValueError):
    """A safe-to-display process-control error."""


@dataclass(frozen=True, slots=True)
class RestartControl:
    schema_version: int
    profile: str
    config_path: str
    pid: int
    instance_id: str
    version: str
    host: str | None = None
    port: int | None = None
    runtime_report_path: str | None = None
    runtime_log_file: str | None = None
    started_at: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version not in {1, CONTROL_SCHEMA_VERSION}:
            raise RestartError("unsupported process control schema_version")
        if not isinstance(self.profile, str) or not self.profile:
            raise RestartError("process control profile must be non-empty")
        if not isinstance(self.config_path, str) or not self.config_path:
            raise RestartError("process control config_path must be non-empty")
        if not Path(self.config_path).is_absolute():
            raise RestartError("process control config_path must be absolute")
        if not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid <= 0:
            raise RestartError("process control pid must be positive")
        if not isinstance(self.instance_id, str) or not self.instance_id:
            raise RestartError("process control instance_id must be non-empty")
        if not isinstance(self.version, str) or not self.version:
            raise RestartError("process control version must be non-empty")
        if self.schema_version == 1:
            return
        if not isinstance(self.host, str) or not self.host:
            raise RestartError("process control host must be non-empty")
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65535
        ):
            raise RestartError("process control port must be between 1 and 65535")
        for field_name in ("runtime_report_path", "runtime_log_file"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise RestartError(f"process control {field_name} must be absolute")
        if not isinstance(self.started_at, str) or not self.started_at:
            raise RestartError("process control started_at must be non-empty")

    def to_dict(self) -> dict[str, str | int | None]:
        value = asdict(self)
        if self.schema_version == 1:
            return {key: item for key, item in value.items() if key in _CONTROL_FIELDS_V1}
        return value

    @classmethod
    def from_dict(cls, value: Any) -> RestartControl:
        if not isinstance(value, dict):
            raise RestartError("process control document has invalid fields")
        schema_version = value.get("schema_version")
        expected_fields = _CONTROL_FIELDS_V1 if schema_version == 1 else _CONTROL_FIELDS_V2
        if set(value) != expected_fields:
            raise RestartError("process control document has invalid fields")
        try:
            return cls(**value)
        except TypeError as exc:
            raise RestartError("process control document has invalid fields") from exc


def control_path(runtime_report_path: Path | None) -> Path:
    if runtime_report_path is None:
        raise RestartError("profile has no runtime_report_path; process control is unavailable")
    return runtime_report_path.with_name(runtime_report_path.name + ".control")


def write_control(path: Path, control: RestartControl) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(control.to_dict(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_control(
    path: Path,
    *,
    expected_profile: str | None = None,
    expected_config_path: Path | None = None,
) -> RestartControl:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RestartError("no running Irigate server control document was found") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RestartError("invalid process control document") from exc

    control = RestartControl.from_dict(value)
    if expected_profile is not None and control.profile != expected_profile:
        raise RestartError("process control profile does not match selected profile")
    if expected_config_path is not None:
        expected = str(expected_config_path.resolve())
        if control.config_path != expected:
            raise RestartError(
                "process control configuration path does not match selected profile"
            )
    return control


def remove_control(path: Path, instance_id: str) -> bool:
    try:
        control = read_control(path)
    except RestartError:
        return False
    if control.instance_id != instance_id:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def process_is_irigate(pid: int, *, proc_root: Path = Path("/proc")) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    arguments = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
    if not arguments:
        return False
    executable = Path(arguments[0]).name
    if executable == "irigate" or executable.startswith("irigate-"):
        return True
    if executable.startswith(("python", "pypy")) and len(arguments) > 1:
        script = Path(arguments[1]).name
        if script == "irigate" or script.startswith("irigate-"):
            return True
    return any(
        arguments[index : index + 2] == ["-m", "irigate"]
        for index in range(1, len(arguments) - 1)
    )


def _read_running_control(
    path: Path,
    *,
    expected_profile: str,
    expected_config_path: Path,
    process_check: Callable[[int], bool],
) -> RestartControl:
    control = read_control(
        path,
        expected_profile=expected_profile,
        expected_config_path=expected_config_path,
    )
    if not process_check(control.pid):
        raise RestartError("recorded process is not a running Irigate instance")
    return control


def reload_running(
    path: Path,
    *,
    expected_profile: str,
    expected_config_path: Path,
    process_check: Callable[[int], bool] = process_is_irigate,
    kill: Callable[[int, int], None] = os.kill,
) -> RestartControl:
    """Request an immediate config reload from the exact claimed Irigate instance."""

    control = _read_running_control(
        path,
        expected_profile=expected_profile,
        expected_config_path=expected_config_path,
        process_check=process_check,
    )
    try:
        kill(control.pid, signal.SIGHUP)
    except OSError as exc:
        raise RestartError("failed to signal the running Irigate instance") from exc
    return control


def stop_running(
    path: Path,
    *,
    expected_profile: str,
    expected_config_path: Path,
    process_check: Callable[[int], bool] = process_is_irigate,
    kill: Callable[[int, int], None] = os.kill,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 0.05,
) -> RestartControl:
    """Gracefully stop the exact Irigate instance claimed by a control document."""

    control = _read_running_control(
        path,
        expected_profile=expected_profile,
        expected_config_path=expected_config_path,
        process_check=process_check,
    )
    try:
        kill(control.pid, signal.SIGTERM)
    except OSError as exc:
        raise RestartError("failed to signal the running Irigate instance") from exc

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            current = read_control(path)
        except RestartError:
            if not path.exists():
                return control
            raise
        if current.instance_id != control.instance_id:
            raise RestartError("running Irigate instance changed during shutdown")
        time.sleep(poll_interval_seconds)
    raise RestartError("stop signal was sent but shutdown was not observed")

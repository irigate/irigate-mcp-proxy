# Changelog

All notable changes to Irigate are documented here. Releases follow Semantic Versioning.

## Unreleased

## [0.5.1] - 2026-07-29

Irigate 0.5.1 fixes two reliability boundaries: systemd now retains the uv tool environment that owns the installed broker, and MCP application errors no longer degrade a healthy shared upstream.

### Fixed

- `irigate systemd setup` and `sync` preserve a symlinked uv tool interpreter path in the generated unit instead of resolving it to a base Python environment where Irigate is not installed.
- Tool-level MCP application errors remain visible as failed calls but no longer increment a shared upstream's failure or crash counters, so they cannot open its degradation breaker.

### Upgrade notes

- After upgrading a systemd-managed 0.5.0 installation, run `irigate systemd sync --config <profile>` from a shell with every referenced environment value. If it reports `restarted=false`, run `systemctl --user start irigate.service` to start the rewritten unit.

## [0.5.0] - 2026-07-28

Irigate 0.5.0 adds a systemd user-service workflow for durable local broker operation without putting credentials in a unit file.

### Added

- `irigate systemd setup`, `sync`, and `reload` manage a fixed `irigate.service` user unit, mirror only referenced broker environment variables into a mode-`0600` environment file, and distinguish environment-refresh restarts from connection-preserving profile reloads.
- Operator documentation for service start, stop, restart, status, journal inspection, enable/disable, profile reload, environment synchronization, and removal.

### Upgrade notes

- Run `irigate systemd setup --config <profile>` once to install and enable the user service. Existing foreground brokers are not adopted automatically.
- Use `irigate systemd sync --config <profile>` after referenced environment values change; it restarts an active service because reload cannot alter a process environment.
- Use `systemctl --user restart irigate.service` after upgrading Irigate or changing startup-bound listener or runtime-path fields.

## [0.4.2] - 2026-07-26

Irigate 0.4.2 republishes the current README to PyPI and makes the project mark load from an absolute public URL.

### Fixed

- PyPI now renders the Irigate logo instead of resolving its relative source against the package index.
- The PyPI project description includes the latest README updates, including WSL/Windows bridging support.

## [0.4.1] - 2026-07-26

Irigate 0.4.1 moves the supported installation path to PyPI. Runtime behavior is unchanged from 0.4.0.

### Added

- MIT license terms and SPDX-compatible PyPI license metadata.

### Changed

- `uv tool install irigate` and `pip install irigate` are the supported release-install commands.
- Releases are immutable `vX.Y.Z` tags: GitHub Actions tests and builds the distributions, publishes them through PyPI Trusted Publishing, then creates the matching GitHub Release with those exact artifacts.

### Upgrade notes

- Replace direct GitHub wheel URLs with `uv tool install --force irigate` or `python -m pip install --upgrade irigate`.
- Existing 0.4.0 installations keep the same runtime behavior; no profile migration is required.

## [0.4.0] - 2026-07-26

Irigate 0.4.0 makes filesystem arguments reliable when WSL agents call Windows-native MCP servers. Profiles retain explicit, auditable path mappings, while `irigate doctor` derives those mappings from each configured server's live tool schemas instead of requiring users to inspect schemas manually.

### Highlights

#### Translate only declared MCP request fields

`wsl_path_arguments` maps exact upstream tool names—or `*`—to JSON Pointers in their request objects. Irigate deep-copies each call and translates only those declared POSIX paths at the worker boundary. Windows paths, missing optional fields, and empty values remain unchanged; configured non-string values fail closed.

#### Configure mappings from live schemas

`irigate doctor` starts only upstreams declared with `execution: wsl-windows`, inspects their advertised input schemas, and reports missing file or directory fields. `doctor --apply` merges the findings into the profile without replacing operator-authored mappings or unrelated YAML text, validates the result before replacement, and creates a first-repair backup.

#### Keep callers and troubleshooting evidence WSL-native

Workspace process arguments receive the same WSL-to-Windows conversion. Protected MCP payload logs retain the original client-facing arguments, while Windows upstreams receive the translated worker-local copy. Slash-prefixed drive paths emitted by some Windows applications, such as `/C:/Users/example/design.pen`, are normalized directly rather than misrouted through `wslpath`.

### Added

- Explicit `wsl_path_arguments` JSON-pointer mappings for translating selected POSIX tool-call paths before dispatch to `wsl-windows` upstreams.
- Automatic Windows-path rendering for canonical `{workspace}` process arguments on `wsl-windows` upstreams.
- `irigate doctor` schema discovery and `--apply` repair for WSL-to-Windows path mappings, with comment-preserving atomic writes and a first-repair backup.

### Changed

- Slash-prefixed Windows drive paths are normalized to native drive paths before dispatch.
- MCP payload logs preserve pre-transformation request arguments for WSL-side diagnosis.
- The bundled benchmark Windows Chrome profile maps its documented file and report output fields.

### Upgrade notes

- Existing native upstreams require no profile changes.
- For every `execution: wsl-windows` upstream, run `irigate doctor --config <profile>` and apply reported mappings with `--apply`.
- `path_arguments` is not accepted; use the explicit `wsl_path_arguments` field.
- Reload the profile after applying mappings. Restart long-running Irigate processes after upgrading so they import the 0.4.0 runtime.

### Installation

```bash
uv tool install "https://github.com/irigate/irigate-mcp-proxy/releases/download/v0.4.0/irigate-0.4.0-py3-none-any.whl"
irigate --version
```

## [0.3.0] - 2026-07-26

Irigate 0.3.0 is the first tagged GitHub release. It turns selected local stdio MCP servers into one loopback Streamable HTTP endpoint while keeping process sharing explicit and context-bound servers isolated. This release adds the operational layer needed for long-running daily use, including reliable Windows MCP launches from WSL.

### Highlights

#### Windows MCP servers without stale WSL pipes

Windows-native upstreams can declare `execution: wsl-windows`. Irigate refreshes the live WSL interop socket before every spawn, so brokers keep launching applications such as Pencil after the shell that started Irigate exits. Missing interop now produces an actionable restart instruction instead of a raw `Broken pipe` failure.

#### Operate the broker without process guesswork

The CLI now exposes version, status, reload, stop, process, and log operations. Runtime state uses an XDG state directory by default, and credential-free control documents identify the effective server instance, listener, profile, report, and active payload log.

#### Troubleshooting evidence when a tool misbehaves

Every serving start and valid direct CLI call writes a private, start-scoped MCP payload log with bounded rotation. `irigate logs` locates the latest file and `irigate logs -f` follows one start without mixing records from later restarts. Payload logs are intentionally sensitive local artifacts; metadata-only audit and runtime-report guarantees remain unchanged.

#### Progressive discovery without hiding exact tool names

The bundled Agent Skill can discover configured upstreams, list one upstream's brief tool metadata, inspect one exact schema, and invoke one exact namespaced tool. Approval and audit surfaces still see the real `<upstream>__<tool>` name; Irigate does not add an opaque dispatcher.

### Added

- Explicit `native` and `wsl-windows` upstream execution modes.
- Per-spawn WSL interop endpoint refresh for Windows executables.
- Safe launch diagnostics when no live WSL interop endpoint exists.
- Tool-level handling for MCP application errors; connection loss remains a process failure.
- `irigate reload`, `irigate stop`, `irigate status`, `irigate ps`, and `irigate logs` operational commands.
- Rotating, permission-restricted MCP payload logs.
- Optional progressive-disclosure Agent Skill and CLI discovery surface.
- Effective broker state, listener, configuration, runtime report, and log location in status output.

### Changed

- Omitted `runtime_report_path` now resolves to `${XDG_STATE_HOME:-~/.local/state}/irigate/<profile>/runtime-report.json`.
- Relative runtime report paths resolve from the selected profile directory.
- Long-running installed console scripts are recognized as Irigate processes during reload and stop validation.
- Windows application errors such as Pencil's “document must be open” response count as tool failures rather than crashes.

### Upgrade notes

- Existing native upstreams require no profile change; `execution` defaults to `native`.
- Add `execution: wsl-windows` to every Windows-native command launched by a WSL broker.
- Restart long-running Irigate processes after upgrading so they import the 0.3.0 runtime.
- Check `irigate status` for the effective XDG runtime-report and payload-log locations.
- Treat files reported by `irigate logs` as sensitive because they contain complete MCP call arguments and responses.

### Installation

Download and install the release wheel directly from GitHub:

```bash
uv tool install "https://github.com/irigate/irigate-mcp-proxy/releases/download/v0.3.0/irigate-0.3.0-py3-none-any.whl"
irigate --version
```

[0.5.1]: https://github.com/irigate/irigate-mcp-proxy/releases/tag/v0.5.1
[0.5.0]: https://github.com/irigate/irigate-mcp-proxy/releases/tag/v0.5.0
[0.4.2]: https://github.com/irigate/irigate-mcp-proxy/releases/tag/v0.4.2
[0.4.1]: https://github.com/irigate/irigate-mcp-proxy/releases/tag/v0.4.1
[0.4.0]: https://github.com/irigate/irigate-mcp-proxy/releases/tag/v0.4.0
[0.3.0]: https://github.com/irigate/irigate-mcp-proxy/releases/tag/v0.3.0

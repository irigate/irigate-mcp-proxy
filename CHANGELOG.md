# Changelog

All notable changes to Irigate are documented here. Releases follow Semantic Versioning.

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

[0.3.0]: https://github.com/irigate/irigate-mcp-proxy/releases/tag/v0.3.0

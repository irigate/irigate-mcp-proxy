# src/irigate

## Purpose

Production Irigate package: validated configuration, loopback MCP transport, deterministic namespaced routing, upstream lifecycle, qualification, and metadata-only reporting.

## Ownership

- `models.py` owns typed static configuration and fail-closed field validation.
- `config.py` owns duplicate-safe YAML loading and broker-environment resolution.
- `__main__.py` owns serving, validation, qualification, runtime tool discovery, direct tool-call, and process-report console contracts.
- `app.py` owns the loopback Streamable HTTP application, agent-label propagation, Origin policy, and background profile watcher.
- `broker.py` owns selection-scoped deferred activation, tool aggregation, exact namespaced routing, worker selection, and atomic upstream reload.
- `selection.py` owns typed agent selector parsing, normalization, and fail-closed set computation.
- `upstream.py` owns one stdio process/session worker, bounded calls, and exact call activity transitions.
- `qualification.py` owns generic checks and reviewed upstream-specific sharing admission.
- `runtime_report.py` owns metadata-only counters and atomic JSON snapshots.
- `audit.py` owns one metadata-only JSON-line record per completed or rejected call.

## Local Contracts

- Bind addresses are loopback-only.
- Upstream transport is stdio-only; changing the transport requires an explicit design decision and updates to `IMPLEMENTATION.md`.
- Profile environment values are `${ENV_NAME}` references only; values come from the broker process and never appear in validation output.
- Profile path precedence is explicit `--config`, then `IRIGATE_CONFIG`, then `~/.config/irigate/config.yaml`.
- `shareable: true` requires a registered upstream-specific qualifier.
- Unknown fields and duplicate YAML keys are errors.
- `serial` and `parallel` concurrency are explicit per-upstream contracts.
- Non-shareable workers are keyed by downstream session and never reused across sessions.
- Every upstream declares a positive `idle_timeout_seconds`; each shared or isolated worker expires independently when it has no queued or active calls and is recreated on demand.
- Shutdown closes the HTTP session manager before workers and bounds active-call draining.
- Requested sharing defaults to isolated when qualification fails; strict mode aborts startup.
- Qualification probes use fixed non-destructive surfaces and never forward client payloads.
- Runtime reports contain counts, durations, modes, activity state, idle timing, upstream keys, and validated agent labels only.
- A degraded shared upstream remains degraded until process restart.
- Audit records contain timestamp, upstream key, tool name, outcome, and duration only.
- Arguments, results, environment values, commands, and credentials never enter audit records.
- Reload prepares changed active upstreams before routing switches, keeps added and changed dormant upstreams unstarted, preserves the last valid active configuration on failure, and never replaces downstream HTTP sessions.
- Runtime `host` and `port` changes are rejected; they require replacing the listener.
- A request without a selector uses all configured upstreams. A selected request uses one `tools` or `upstreams` mode; upstream exclusions override inclusions and unknown names fail closed.
- Qualification, schema discovery, and process startup occur only when an agent first selects an upstream; concurrent first selection is single-flight per upstream.
- Exact tool selectors filter `tools/list` and dispatch; process-wide activation by another agent never broadens a request's selection.
- Direct CLI calls accept one JSON object, emit the complete MCP result as JSON, return nonzero for tool errors, and close their worker before exiting.
- Downstream `agent` labels are explicit attribution metadata, not authentication; omitted labels are `anonymous` and Irigate never infers identity.
- `ps` reads the latest runtime report without resolving environments or starting upstreams and reports busy/idle/stopped state, elapsed idle time, configured idle timeout, and usage in table or JSON form.

## Work Guidance

- Keep configuration parsing free of process startup side effects.
- Return typed models from public loaders; do not pass raw YAML mappings into runtime code.
- Error messages may identify fields and environment-variable names, never resolved values. Missing required broker fields include credential-free, actionable profile examples.
- Runtime tool discovery prints namespaced tool names only and closes every worker before returning.
- Direct CLI tool arguments must not carry credentials; use profile environment references.

## Verification

- `uv run --frozen pytest -q`
- `uv run --frozen python -m irigate --config profiles/mvp.yaml --check`

## Child DOX Index

None.

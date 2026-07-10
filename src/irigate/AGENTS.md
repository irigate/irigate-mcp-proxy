# src/irigate

## Purpose

Production Irigate package: validated configuration, loopback MCP transport, deterministic namespaced routing, upstream lifecycle, qualification, and metadata-only reporting.

## Ownership

- `models.py` owns typed static configuration and fail-closed field validation.
- `config.py` owns duplicate-safe YAML loading and broker-environment resolution.
- `__main__.py` owns the `irigate` console contract.
- `app.py` owns the loopback Streamable HTTP application and Origin policy.
- `broker.py` owns tool aggregation, exact namespaced routing, and worker selection.
- `upstream.py` owns one stdio process/session worker and bounded calls.
- `qualification.py` owns generic checks and reviewed upstream-specific sharing admission.
- `runtime_report.py` owns metadata-only counters and atomic JSON snapshots.
- `audit.py` owns one metadata-only JSON-line record per completed or rejected call.

## Local Contracts

- Bind addresses are loopback-only.
- Upstream transport is stdio-only until the implementation plan explicitly adds another transport.
- Profile environment values are `${ENV_NAME}` references only; values come from the broker process and never appear in validation output.
- `shareable: true` requires a registered upstream-specific qualifier.
- Unknown fields and duplicate YAML keys are errors.
- `serial` and `parallel` concurrency are explicit per-upstream contracts.
- Non-shareable workers are keyed by downstream session and never reused across sessions.
- Shutdown closes the HTTP session manager before workers and bounds active-call draining.
- Requested sharing defaults to isolated when qualification fails; strict mode aborts startup.
- Qualification probes use fixed non-destructive surfaces and never forward client payloads.
- Runtime reports contain counts, durations, modes, and upstream keys only.
- A degraded shared upstream remains degraded until process restart.
- Audit records contain timestamp, upstream key, tool name, outcome, and duration only.
- Arguments, results, environment values, commands, and credentials never enter audit records.

## Work Guidance

- Keep configuration parsing free of process startup side effects.
- Return typed models from public loaders; do not pass raw YAML mappings into runtime code.
- Error messages may identify fields and environment-variable names, never resolved values.

## Verification

- `uv run --frozen pytest -q`
- `uv run --frozen python -m irigate --config profiles/mvp.yaml --check`

## Child DOX Index

None.

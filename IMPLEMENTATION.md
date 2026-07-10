---
title: Irigate implementation and extension contracts
status: active
---

# Irigate implementation and extension contracts

## Product boundary

Irigate is a loopback-only MCP broker for local developer workflows. It lets multiple local agent sessions share explicitly qualified stdio MCP servers while preserving isolated-by-default behavior and emitting metadata-only operational evidence.

It is not an enterprise gateway. Remote access, tenant identity, authorization, OAuth, TLS termination, Kubernetes deployment, model-API proxying, dynamic configuration, payload inspection, and compliance claims are outside the product boundary.

## Runtime architecture

1. `config.load_config()` parses a static YAML profile into typed models, rejects duplicate keys and unknown fields, and resolves only `${ENV_NAME}` references from the broker process environment.
2. `app.create_app()` exposes MCP Streamable HTTP on a loopback address and enforces the Origin policy. Local non-browser clients may omit `Origin`; malformed or non-loopback origins are rejected.
3. `Broker` initializes configured upstreams, aggregates `tools/list`, and routes exact `<upstream-key>__<tool-name>` calls.
4. `Broker` selects a shared worker only when sharing was requested and qualification passed. Otherwise it creates workers scoped to downstream sessions.
5. `UpstreamWorker` owns one stdio MCP process/session, concurrency control, bounded calls, and termination.
6. `RuntimeMetrics` records metadata-only counters and atomically refreshes the configured JSON report.
7. `AuditLog` writes exactly one metadata-only JSON-line record for every completed or rejected call.

## Configuration contract

Profiles define:

- Loopback host and port.
- Upstream key, stdio command, arguments, and environment references.
- Explicit `shareable` mode and qualifier name.
- Explicit `serial` or `parallel` concurrency.
- Call timeout and degradation thresholds.
- Optional runtime-report path.

Constraints:

- Upstream keys are unique and valid routing prefixes.
- Commands and arguments must not carry credentials.
- Environment values are references, never literal secrets.
- Unknown environment references fail during loading.
- `shareable: true` requires a registered upstream-specific qualifier.
- Unknown fields, duplicate YAML keys, unsupported transports, and non-loopback binds are errors.

## Sharing and qualification

MCP transport behavior cannot prove that an upstream is semantically safe to share. Admission therefore combines generic protocol checks with an explicit qualifier:

- Generic checks use two isolated instances to verify initialization, stable tool-schema fingerprints, reconnect behavior, timeout handling, and crash isolation.
- Qualifiers are registered by name and contain only reviewed, non-destructive, upstream-specific probes.
- Failed qualification downgrades the upstream to isolated mode. `--require-qualified-sharing` converts that downgrade into a startup failure.
- A shared upstream that reaches its configured error or crash threshold becomes degraded. New sessions use isolated workers, and shared mode is not restored until restart.

Context7 is the qualified shared upstream in `profiles/mvp.yaml`. Its qualifier covers its fixed-identity, read-only surface. Code-review-graph remains isolated because it retains context-bound state. An upstream with no reviewed qualifier remains isolated.

## Session, concurrency, and shutdown contracts

- Non-shareable workers are keyed by downstream session and are never reused across sessions.
- Shared workers are reused only within one broker process and only after qualification.
- `serial` workers admit one call at a time; `parallel` workers permit concurrent calls.
- Locks are per upstream. A slow or failed upstream must not block unrelated upstreams.
- Calls have bounded timeouts and report queue and call durations separately.
- Shutdown stops new work, bounds active-call draining, closes MCP sessions, terminates child processes, and kills only children that outlive the termination interval.
- Client disconnects and repeated broker lifecycles must leave no orphan upstream processes.

## Routing contract

Exposed tools use `<upstream-key>__<tool-name>`. Listing and dispatch use the same exact namespace. Unknown prefixes and unknown tool names are rejected; routing never uses first-match behavior.

## Evidence boundaries

Audit records contain timestamp, upstream key, tool name, duration, and outcome. Runtime reports contain modes, qualification state, counts, durations, failures, crashes, reuse, and avoided-instance evidence.

Neither surface may contain arguments, results, environment values, commands, authorization headers, credentials, or hashes of low-entropy secrets. Runtime reports may claim consolidation only when multiple logical clients reused a qualified worker.

## Module ownership

- `src/irigate/models.py` — typed configuration and field validation.
- `src/irigate/config.py` — duplicate-safe YAML loading and environment-reference resolution.
- `src/irigate/app.py` — loopback Streamable HTTP application and Origin enforcement.
- `src/irigate/broker.py` — tool aggregation, exact routing, worker selection, degradation, and shutdown coordination.
- `src/irigate/upstream.py` — stdio worker lifecycle, concurrency, bounded calls, and process cleanup.
- `src/irigate/qualification.py` — generic checks, qualifier registry, and sharing admission.
- `src/irigate/runtime_report.py` — counters and atomic metadata-only snapshots.
- `src/irigate/audit.py` — one metadata-only call record per outcome.
- `src/irigate/__main__.py` — `--check`, `qualify`, and serving CLI contracts.
- `profiles/` — static runtime and benchmark profiles.
- `scripts/` — compatibility and resource-measurement harnesses.
- `tests/` — executable contracts and credential-free MCP fixtures.
- `spikes/` — disposable transport and upstream probes; production code must not depend on them.

## Extension rules

### Add an upstream profile

1. Add a unique key and stdio command to a profile without literal credentials.
2. Default to `shareable: false`.
3. Select `serial` unless parallel safety is established.
4. Run profile checking and the relevant compatibility harness.

### Admit a shareable upstream

1. Identify a fixed, non-destructive probe surface.
2. Add a named qualifier in `qualification.py`; do not infer safety from tool annotations or names.
3. Test generic qualification failure, qualifier failure, strict startup, and isolated fallback.
4. Test concurrent sessions for state visibility and process reuse.
5. Add the qualifier name to the profile only after those tests pass.
6. Benchmark identical and context-bound sessions separately; never extrapolate sharing results across credentials or workspaces.

### Add configuration

1. Extend the typed model with an explicit default or required field.
2. Keep unknown-field rejection intact.
3. Thread the typed value through runtime code; do not pass raw YAML mappings.
4. Add valid, invalid, default, and output-redaction tests.
5. Update profiles and the owning DOX contract when responsibilities or constraints change.

### Add telemetry

1. Establish why metadata is operationally necessary.
2. Keep payloads and environment values out of all records.
3. Add sentinel tests covering arguments, results, and broker environment values.
4. Preserve one audit record per call outcome and atomic runtime-report writes.

### Add a transport or remote boundary

Do not extend the current architecture incrementally for this. Remote bind, authentication, authorization, TLS, or a second downstream transport changes the security and product boundary and requires a separate design decision before implementation.

## Verification

Canonical local checks:

```bash
uv run --frozen pytest -q
uv run --frozen python -m irigate --config profiles/mvp.yaml --check
uv run --frozen python -m irigate --config profiles/benchmark-heavy.yaml --check
```

Environment-dependent evidence checks:

```bash
uv run --frozen python -m irigate qualify --config profiles/mvp.yaml
uv run --frozen python scripts/compatibility.py --config profiles/mvp.yaml
uv run --frozen python scripts/benchmark.py --config profiles/benchmark-heavy.yaml --clients 1,5,20 --repetitions 3
```

The full test suite must prove loopback enforcement, exact routing, qualification fallback, session isolation, concurrency modes, bounded shutdown, orphan cleanup, report reconciliation, and payload-free audit output.

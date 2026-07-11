---
title: Irigate implementation and extension contracts
status: active
---

# Irigate implementation and extension contracts

## Product boundary

Irigate is a loopback-only MCP broker for local developer workflows. It lets multiple local agent sessions share explicitly qualified stdio MCP servers while preserving isolated-by-default behavior and emitting metadata-only operational evidence.

It is not an enterprise gateway. Remote access, tenant identity, authorization, OAuth, TLS termination, Kubernetes deployment, model-API proxying, remote configuration APIs, payload inspection, and compliance claims are outside the product boundary.

## Runtime architecture

1. `config.load_config()` parses a YAML profile into typed models, rejects duplicate keys and unknown fields, and resolves only `${ENV_NAME}` references from the broker process environment.
2. `app.create_app()` exposes MCP Streamable HTTP on a loopback address, enforces the Origin policy, and watches the selected profile for background reloads. Local non-browser clients may omit `Origin`; malformed or non-loopback origins are rejected.
3. `Broker` validates each agent selection, activates only selected upstreams, filters `tools/list`, routes exact `<upstream-key>__<tool-name>` calls, and atomically swaps successfully prepared active-upstream changes.
4. `Broker` selects a shared worker only when sharing was requested and qualification passed. Otherwise it creates workers scoped to downstream sessions.
5. `UpstreamWorker` owns one stdio MCP process/session, concurrency control, bounded calls, per-process idle expiry, and termination.
6. `RuntimeMetrics` records metadata-only counters and atomically refreshes the configured JSON report.
7. `AuditLog` writes exactly one metadata-only JSON-line record for every completed or rejected call.

## Configuration contract

Profiles define:

- Loopback host and port.
- Upstream key, stdio command, arguments, and environment references.
- Explicit `shareable` mode and qualifier name.
- Explicit `serial` or `parallel` concurrency.
- Required per-upstream idle timeout, call timeout, and degradation thresholds.
- Optional runtime-report path.

Constraints:

- Upstream keys are unique and valid routing prefixes.
- Commands and arguments must not carry credentials.
- Environment values are references, never literal secrets.
- Unknown environment references fail during loading.
- `shareable: true` requires a registered upstream-specific qualifier.
- Unknown fields, duplicate YAML keys, unsupported transports, and non-loopback binds are errors.

Runtime reload behavior:

- The profile file is polled in the background while serving.
- Changed active upstreams must initialize successfully before the active routing table changes; added and changed dormant upstreams remain stopped.
- A successful reload retires only changed active or removed upstream workers. Existing downstream Streamable HTTP sessions remain connected and selectors are evaluated against the refreshed profile.
- Invalid files, missing environment references, and failed upstream initialization leave the last valid configuration active.
- `host` and `port` changes are rejected at runtime because they require replacing the listening socket.

## Sharing and qualification

MCP transport behavior cannot prove that an upstream is semantically safe to share. Admission therefore combines generic protocol checks with an explicit qualifier:

- Generic checks use two isolated instances to verify initialization, stable tool-schema fingerprints, reconnect behavior, timeout handling, and crash isolation.
- Qualifiers are registered by name and contain only reviewed, non-destructive, upstream-specific probes.
- Failed qualification downgrades the selected upstream to isolated mode. `--require-qualified-sharing` rejects its first selected use.
- A shared upstream that reaches its configured error or crash threshold becomes degraded. New sessions use isolated workers, and shared mode is not restored until restart.

Context7 is the qualified shared upstream in `profiles/mvp.yaml`. Its qualifier covers its fixed-identity, read-only surface. Code-review-graph remains isolated because it retains context-bound state. An upstream with no reviewed qualifier remains isolated.

## Session, concurrency, and shutdown contracts

- Non-shareable workers are keyed by downstream session and are never reused across sessions.
- Shared workers are reused only within one broker process and only after qualification.
- `serial` workers admit one call at a time; `parallel` workers permit concurrent calls.
- Locks are per upstream. A slow or failed upstream must not block unrelated upstreams.
- Calls have bounded timeouts and report queue and call durations separately.
- Every worker shuts down independently after `idle_timeout_seconds` with no queued or active calls. The next call creates a fresh worker in the same effective sharing mode.
- Shutdown stops new work, bounds active-call draining, closes MCP sessions, terminates child processes, and kills only children that outlive the termination interval.
- Client disconnects and repeated broker lifecycles must leave no orphan upstream processes.
- Reload drains retired workers after the replacement routing table is active; unchanged workers continue without restart.

## Routing contract

Exposed tools use `<upstream-key>__<tool-name>`. Listing and dispatch use the same exact namespace. Unknown prefixes and unknown tool names are rejected; routing never uses first-match behavior.

Every downstream URL may omit selection to expose all configured upstreams unchanged, or supply one selector:

- `tools=a__x,b__y` activates only referenced upstreams and exposes only the exact tools.
- `upstreams=a,b` exposes every tool from the positive set.
- `upstreams=!a,!b` starts from all configured upstreams and subtracts exclusions.
- Mixed upstream selectors use positive-base-minus-exclusions semantics; exclusion always wins.
- `agent=<name>` may accompany either selector or the bare endpoint and attributes valid tool calls to an explicit downstream label.

Unknown positive or reverse names, repeated parameters, malformed tokens, unrelated query parameters, invalid or repeated agent labels, and empty final sets fail closed. Agent labels are attribution metadata rather than authentication; omitted labels use `anonymous`, and identity is never inferred from headers. Reverse-only selection may broaden after reload when the profile adds an upstream. Selection is enforced per request even when another agent already activated the same process. Concurrent first activation is single-flight per upstream.

## Evidence boundaries

Audit records contain timestamp, upstream key, tool name, duration, and outcome. Runtime report schema version 2 contains modes, qualification state, live instances, counts, durations, failures, crashes, reuse, avoided-instance evidence, and per-agent call/failure counts by upstream.

Neither surface may contain arguments, results, environment values, commands, authorization headers, credentials, or hashes of low-entropy secrets. Runtime reports may claim consolidation only when multiple logical clients reused a qualified worker.

## Module ownership

- `src/irigate/models.py` — typed configuration and field validation.
- `src/irigate/config.py` — duplicate-safe YAML loading and environment-reference resolution.
- `src/irigate/app.py` — loopback Streamable HTTP application, selector and agent-label propagation, Origin enforcement, and profile watching.
- `src/irigate/broker.py` — deferred activation, selection-scoped tool aggregation, exact routing, worker selection, atomic reload, degradation, and shutdown coordination.
- `src/irigate/selection.py` — typed selector parsing, normalization, and fail-closed set computation.
- `src/irigate/upstream.py` — stdio worker lifecycle, concurrency, bounded calls, and process cleanup.
- `src/irigate/qualification.py` — generic checks, qualifier registry, and sharing admission.
- `src/irigate/runtime_report.py` — counters and atomic metadata-only snapshots.
- `src/irigate/audit.py` — one metadata-only call record per outcome.
- `src/irigate/__main__.py` — `--check`, runtime tool discovery, direct tool calls, `ps`, `qualify`, and serving CLI contracts.
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
4. Add valid, invalid, required-field, and output-redaction tests.
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
uv run --frozen python -m irigate tools --config profiles/mvp.yaml
uv run --frozen python -m irigate call --config profiles/mvp.yaml <upstream>__<tool> --arguments '{}'
uv run --frozen python -m irigate ps --config profiles/mvp.yaml
uv run --frozen python -m irigate qualify --config profiles/mvp.yaml
uv run --frozen python scripts/compatibility.py --config profiles/mvp.yaml
uv run --frozen python scripts/benchmark.py --config profiles/benchmark-heavy.yaml --clients 1,5,20 --repetitions 3
```

The full test suite must prove default-all behavior, selected-only activation, exact filtering and routing, qualification fallback, session isolation, connection-preserving selection-aware reload, failed-reload fallback, concurrency modes, bounded shutdown, orphan cleanup, report reconciliation, and payload-free audit output.

`irigate tools --config <profile>` initializes every configured upstream, prints one namespaced tool name per line, and closes all discovery workers before exiting. It is runtime discovery rather than static validation, so package downloads, network access, and referenced environment variables may be required.

`irigate call --config <profile> <upstream>__<tool> [--arguments <JSON-object>]` invokes one namespaced tool without opening the HTTP listener. It writes the complete MCP result as JSON, maps successful/tool-error results to exit codes `0`/`1`, rejects malformed or non-object arguments with exit code `2`, and closes the selected worker before exiting. Credentials remain broker-process environment values and must not be supplied in tool arguments.

`irigate ps --config <profile> [--json]` reads the configured runtime report without resolving upstream environment references or starting processes. The table emits one upstream/agent row with effective mode, live instances, calls, and failures; JSON mode preserves the complete snapshot. Process liveness reflects the latest atomic write, while usage counters cover only the broker run represented by that report.

---
title: Irigate local MCP broker — implementation plan
status: active
---

# Irigate local MCP broker — implementation plan

> For Hermes: implement this plan phase by phase. Stop at every gate; do not continue when a gate fails.

## Goal

Validate and, only if the evidence supports it, implement a loopback-only MCP broker that lets multiple local AI coding-agent sessions share explicitly approved stdio MCP servers while preserving session correctness and producing metadata-only call telemetry.

## Execution state

- [ ] Phase 0 — transport and sharing spikes (in progress)
- [ ] Phase 1 — package and configuration contract
- [ ] Phase 2 — broker core and deterministic routing
- [ ] Phase 3 — concurrency, isolation, and shutdown
- [ ] Phase 4 — runtime qualification and goal report
- [ ] Phase 5 — metadata audit trail
- [ ] Phase 6 — compatibility and benchmark evidence
- [ ] Phase 7 — documentation and release decision

Every phase records its exact verification output and gate verdict in its owned artifacts before its completion marker changes to `[x]`. Each completed phase is committed separately with the preferred message produced by the `dev-git-commit-message` workflow. A failed experimental gate leaves later phases open and stops execution; it is not converted into implementation work.

## Product boundary

Irigate is a local developer-infrastructure component, not an enterprise governance platform. The MVP proves one claim: compatible local agent sessions can share selected MCP server processes and reduce process count, memory use, and repeated cold starts without leaking state between sessions.

### MVP capabilities

- One loopback Streamable HTTP MCP endpoint.
- Static YAML configuration loaded at startup.
- Two or three stdio upstreams in the validation profile.
- Explicit `shareable: true` opt-in per upstream; the default is isolated.
- Namespaced tools exposed as `<upstream-key>__<tool-name>`.
- `tools/list` and `tools/call` forwarding.
- Metadata-only JSON-lines audit records.
- Fail-closed startup qualification for every upstream requested as shareable.
- A continuously refreshed runtime report showing whether configured upstreams are actually being reused and whether the resource-saving hypothesis holds for the current workload.
- Foreground process with signal-based graceful shutdown.
- Automated compatibility and benchmark harnesses for 1, 5, and 20 concurrent clients.

### Explicit non-goals

- No SSE client endpoint; Streamable HTTP is the primary downstream transport.
- No credentials in URLs, query parameters, command arguments, logs, or committed profiles.
- No tenant model, per-user authorization, OAuth, TLS termination, or remote bind.
- No custom filesystem MCP server, path-guessing middleware, or regex-based secret rewriting.
- No OpenAI or Anthropic API proxying.
- No daemon/PID-file manager, web portal, dynamic configuration API, hot reload, or Kubernetes deployment.
- No claim of compliance certification, data-loss prevention, or multi-tenant isolation.

## Architectural decisions

### Downstream transport

Expose Streamable HTTP on `127.0.0.1`. Pin an MCP SDK version only after the transport spike proves `initialize`, `tools/list`, and `tools/call` round trips against a real client.

### Upstream lifecycle

Each upstream declares one lifecycle mode:

- `shareable: false` — default; create an instance per downstream client session.
- `shareable: true` — reuse one process only after the upstream passes the shared-state test suite.

Do not infer shareability from transport, command, or tool names. Sharing is an operator decision backed by test evidence.

### Configuration and secrets

Profiles contain commands, arguments, non-secret environment-variable names, and secret references only. Runtime secret values come from the broker process environment or a later secret-provider interface. Unknown references fail at startup. The HTTP API never accepts arbitrary environment overrides.

### Tool routing

Prefix every exposed tool with its upstream key. Reject duplicate upstream keys and invalid key names at startup. Never use first-match routing for collisions.

### Concurrency

Do not put a single global lock around an upstream by default. Record each upstream's concurrency mode:

- `serial` — one call at a time for upstreams known to require it.
- `parallel` — concurrent calls allowed only after validation.

Different upstreams must always progress independently. A timeout or crash in one upstream must not block another.

### Runtime qualification and goal evidence

The broker can verify some properties generically from the MCP protocol, but it cannot infer that an arbitrary server is semantically safe to share. MCP does not declare whether tools are read-only, whether the server retains client state, or which calls would expose cross-session leakage.

Use two distinct mechanisms:

1. **Startup qualification** decides whether a requested shared upstream may enter shared mode.
   - Generic checks spawn two isolated instances, complete `initialize`, compare `tools/list` schema fingerprints, exercise disconnect/reconnect, and verify that one failed instance does not affect another upstream.
   - Behavioral checks are upstream-specific, explicitly named in the profile, and run only against configured safe probes. They test concurrent callers and cross-client state visibility without guessing which arbitrary tools are safe to invoke.
   - `shareable: true` without a known passing qualifier fails closed to isolated mode. A command-line strict flag makes this a startup error instead of a downgrade.
2. **Runtime evidence** measures the actual workload without issuing synthetic tool calls.
   - Track logical client-to-upstream bindings, live child processes, spawn count, reuse hits, startup latency, queue latency, call latency, failures, crashes, and orphan cleanup.
   - Write an atomic, metadata-only JSON report at a configured local path and emit the same summary at shutdown.
   - Report requested mode, qualification result, and effective mode per upstream. Never claim consolidation when only one logical client used an upstream.

Runtime failures can trip a shared upstream into `degraded` state so new client sessions receive isolated instances. This limits further exposure but cannot prove or undo semantic leakage that already occurred. Only an upstream-specific qualifier can admit an upstream to shared mode.

### Audit boundary

Write one JSON object per call to stderr with timestamp, generated client-session ID, upstream key, tool name, duration, outcome, and error class. Never log arguments, results, environment values, authorization headers, or hashes of low-entropy secrets.

## Intended repository layout

```text
pyproject.toml
src/irigate/
  __init__.py
  __main__.py
  app.py
  audit.py
  broker.py
  config.py
  models.py
  qualification.py
  runtime_report.py
  upstream.py
profiles/
  mvp.yaml
  benchmark-heavy.yaml
scripts/
  benchmark.py
  compatibility.py
tests/
  fixtures/echo_server.py
  test_audit.py
  test_broker.py
  test_config.py
  test_isolation.py
  test_qualification.py
  test_routing.py
  test_runtime_report.py
  test_shutdown.py
  test_transport.py
README.md
MARKET-RESEARCH.md
IMPLEMENTATION-PLAN.md
```

The implementation lives in this repository and installs as a normal Python package. Do not write product source into `~/.irigate/`; that directory may hold operator-owned runtime configuration later.

## Phase 0 — transport and sharing spikes

### Objective

Kill the project early if the MCP transport or process-sharing assumptions do not hold.

### Files

- Create `spikes/001-streamable-http-roundtrip/README.md` and disposable spike code.
- Create `spikes/002-shared-upstream-state/README.md` and disposable spike code.
- Create `spikes/003-multi-client-compatibility/README.md` and disposable spike code.

### Work

1. [ ] Pin a candidate Python and MCP SDK version inside each spike, not in production packaging yet.
2. [ ] Prove a Streamable HTTP client can complete `initialize`, `tools/list`, and `tools/call` through a broker into one stdio echo server.
3. [ ] Connect two clients simultaneously and prove responses return to the correct caller.
4. [ ] Run the same test against two real candidate upstreams from the operator's workload.
5. [ ] For every candidate shared upstream, test whether state created by client A is observable by client B.
6. [ ] Test client disconnect, upstream crash, request timeout, and broker shutdown.
7. [ ] Separate properties that can be checked generically from properties requiring an upstream-specific safe probe.
8. [ ] Verify that malformed and non-loopback `Origin` headers are rejected; document and test the explicit no-Origin policy required by supported non-browser local clients.
9. [ ] Record exact commands, versions, results, and a `VALIDATED`, `PARTIAL`, or `INVALIDATED` verdict in each spike README.

### Gate

Continue only if:

- The Streamable HTTP round trip is reliable.
- At least two relevant clients can use it without an SSE bridge.
- At least one expensive stdio upstream is demonstrably safe to share.
- A failed upstream does not stop calls to another upstream.
- Streamable HTTP requests enforce the MCP Origin-validation requirement without accepting remote origins, and the tested no-Origin behavior is documented.

If no expensive upstream is safe to share, stop: the core resource-consolidation value is invalidated.

## Phase 1 — package and configuration contract

### Objective

Create an installable, testable package with fail-closed static configuration.

### Files

- Create `pyproject.toml`.
- Create `src/irigate/__init__.py`, `src/irigate/__main__.py`, `src/irigate/config.py`, and `src/irigate/models.py`.
- Create `tests/test_config.py`.
- Replace the current reference profiles with `profiles/mvp.yaml` and `profiles/benchmark-heavy.yaml`.

### Work

1. [ ] Write failing tests for valid profiles, duplicate keys, invalid commands, missing secret references, unsupported transports, and unknown fields.
2. [ ] Define typed configuration for host, port, upstream key, command, arguments, environment references, `shareable`, qualifier name, concurrency, call timeout, and optional runtime-report path.
3. [ ] Require loopback host values and reject remote binds.
4. [ ] Resolve `${ENV_NAME}` only from the broker process environment and report missing names without printing values.
5. [ ] Reject `shareable: true` when the profile does not name a registered upstream-specific qualifier.
6. [ ] Add a console entry point for `irigate` that loads configuration and exits non-zero on validation errors.

### Verification

```bash
python -m pytest tests/test_config.py -q
python -m irigate --config profiles/mvp.yaml --check
```

Expected: tests pass; `--check` reports profile and upstream names without secret values or starting processes.

## Phase 2 — broker core and deterministic routing

### Objective

Proxy MCP tools without ambiguous routing or implicit process sharing.

### Files

- Create `src/irigate/app.py`, `src/irigate/broker.py`, and `src/irigate/upstream.py`.
- Create `tests/fixtures/echo_server.py`.
- Create `tests/test_transport.py`, `tests/test_routing.py`, and `tests/test_broker.py`.

### Work

1. [ ] Write failing end-to-end tests for downstream `initialize` and Origin validation.
2. [ ] Implement the loopback Streamable HTTP application.
3. [ ] Write a failing test that expects `echo__repeat` from an upstream key `echo`.
4. [ ] Implement upstream initialization and namespaced `tools/list` aggregation.
5. [ ] Write failing tests for unknown prefixes, duplicate names, upstream initialization failure, call timeout, and upstream crash.
6. [ ] Implement exact prefix-based dispatch and isolate upstream failures.
7. [ ] Add per-upstream lifecycle handling for isolated and explicitly shared instances.

### Verification

```bash
python -m pytest tests/test_transport.py tests/test_routing.py tests/test_broker.py -q
```

Expected: all tests pass; no test relies on first-match routing or credentials in request URLs.

## Phase 3 — concurrency, isolation, and shutdown

### Objective

Prove that sharing saves resources without cross-session state leakage.

### Files

- Create `tests/test_isolation.py` and `tests/test_shutdown.py`.
- Extend `src/irigate/upstream.py` and `src/irigate/broker.py`.

### Work

1. [ ] Test simultaneous calls to different upstreams; a slow call must not delay a fast upstream.
2. [ ] Test `serial` and `parallel` concurrency modes independently.
3. [ ] Test that non-shareable upstreams never reuse a process across client sessions.
4. [ ] Run the Phase 0 state-isolation fixtures against every `shareable: true` profile entry.
5. [ ] Implement graceful shutdown: stop accepting clients, bound the drain interval, close MCP sessions, terminate child processes, then kill only remaining children.
6. [ ] Test client disconnects and repeated startup/shutdown cycles for orphan processes.

### Verification

```bash
python -m pytest tests/test_isolation.py tests/test_shutdown.py -q
```

Expected: tests pass and the process table returns to baseline after each test.

## Phase 4 — runtime qualification and goal report

### Objective

Check the selected MCP servers before sharing them and report whether the running workload actually benefits from consolidation.

### Files

- Create `src/irigate/qualification.py` and `src/irigate/runtime_report.py`.
- Create `tests/test_qualification.py` and `tests/test_runtime_report.py`.
- Extend `src/irigate/__main__.py`, `src/irigate/broker.py`, and `src/irigate/upstream.py`.

### Work

1. [ ] Write failing tests proving that an unqualified upstream cannot enter shared mode.
2. [ ] Implement generic startup checks: two isolated initializations, stable tool-schema fingerprint, disconnect/reconnect, timeout, and crash isolation.
3. [ ] Define a small qualifier registry. Each qualifier names the upstream it supports and implements only explicit, reviewed, non-destructive behavioral probes.
4. [ ] Add `irigate qualify --config <path>` to run qualification without serving clients and return non-zero when requested sharing is not admitted.
5. [ ] Run the same qualification during normal startup. Default to isolated mode on failure; `--require-qualified-sharing` instead aborts startup.
6. [ ] Add in-memory counters for logical bindings, live instances, spawns, reuse hits, startup duration, queue duration, call duration, failures, and crashes.
7. [ ] Atomically refresh the configured JSON runtime report without arguments, results, environment values, or credentials.
8. [ ] Mark an upstream `degraded` after configured crash/error thresholds and route new sessions to isolated instances; do not silently restore shared mode during the same run.
9. [ ] Test that a one-client run reports `insufficient_evidence`, a multi-client shared run reports actual avoided instances, and an isolated run never claims consolidation.

### Verification

```bash
python -m pytest tests/test_qualification.py tests/test_runtime_report.py -q
python -m irigate qualify --config profiles/mvp.yaml
```

Expected: only explicitly qualified upstreams are admitted to shared mode; the report distinguishes `qualified`, `degraded`, `isolated`, and `insufficient_evidence` without exposing payload data.

## Phase 5 — metadata audit trail

### Objective

Provide useful operational evidence without collecting tool payloads.

### Files

- Create `src/irigate/audit.py` and `tests/test_audit.py`.

### Work

1. [ ] Write tests for success, timeout, upstream error, invalid tool, and shutdown outcomes.
2. [ ] Implement one JSON-line record per completed or rejected call.
3. [ ] Add tests with sentinel credentials in arguments, results, and environment values.
4. [ ] Assert sentinel values never occur in captured stdout or stderr.

### Verification

```bash
python -m pytest tests/test_audit.py -q
```

Expected: valid JSON records contain metadata only; sentinel values are absent.

## Phase 6 — compatibility and benchmark evidence

### Objective

Determine whether the broker solves a material developer problem.

### Files

- Create `scripts/compatibility.py` and `scripts/benchmark.py`.
- Add measured results to `MARKET-RESEARCH.md` under `Validation evidence`.

### Work

1. [ ] Run direct-versus-broker comparisons with 1, 5, and 20 concurrent clients.
2. [ ] Measure child-process count, resident memory, startup-to-first-tool-list latency, first-call latency, steady-state call latency, error rate, and orphan processes after shutdown.
3. [ ] Run each case repeatedly and report median plus range; do not publish a single favorable run.
4. [ ] Test Hermes, Claude Code, and Codex where their current MCP clients support Streamable HTTP.
5. [ ] Separate results for identical contexts from results using different workspaces or credentials.
6. [ ] Record which real upstreams are safe to share and which require isolation.
7. [ ] Reconcile external benchmark measurements with the broker's runtime report; discrepancies are test failures, not documentation caveats.

### Gate

Proceed to a maintained product only if the measurements show a repeatable, material reduction for a real multi-agent workload and no isolation failure. If savings disappear once sessions require distinct contexts, reposition as a convenience router or stop the project.

## Phase 7 — documentation and release decision

### Objective

Publish only claims supported by the benchmark and compatibility results.

### Files

- Update `README.md`.
- Update `MARKET-RESEARCH.md`.
- Update root and child `AGENTS.md` files if repository responsibilities changed.

### Work

1. [ ] Replace hypothesis language with measured results only where evidence exists.
2. [ ] Document supported clients, supported upstreams, and known unsafe sharing cases.
3. [ ] Keep enterprise identity, compliance, remote deployment, and API-gateway features out of the roadmap unless a paying design partner requires them.
4. [ ] Decide among three outcomes: stop, maintain as an internal tool, or release as an open-source local MCP broker.
5. [ ] Mark this plan `completed` or `stopped`, preserving unfinished items as open evidence gaps.

## Full verification

```bash
python -m pytest -q
python -m irigate --config profiles/mvp.yaml --check
python -m irigate qualify --config profiles/mvp.yaml
python scripts/compatibility.py --config profiles/mvp.yaml
python scripts/benchmark.py --config profiles/benchmark-heavy.yaml --clients 1,5,20
```

Also verify:

- The broker listens only on loopback.
- No URL contains credentials or arbitrary environment overrides.
- Every exposed tool has exactly one upstream prefix.
- Process counts return to baseline after shutdown.
- The runtime report agrees with independently measured process counts and never claims savings from a one-client run.
- Audit output contains no arguments, results, or environment values.
- All Markdown links resolve.

## Principal risks

| Risk | Consequence | Response |
|---|---|---|
| MCP servers retain client-specific state | Cross-session leakage | Default to isolated; require an explicit, tested sharing allowlist |
| Clients lack reliable Streamable HTTP support | Compatibility gap | Record unsupported clients; do not make deprecated SSE the core architecture |
| Distinct workspaces or credentials eliminate sharing | Weak resource savings | Benchmark realistic contexts and stop if savings are immaterial |
| Generic protocol checks are mistaken for proof of semantic isolation | Cross-session leakage despite a green health check | Require a reviewed upstream-specific qualifier before shared mode |
| One upstream serializes all work | Poor multi-agent throughput | Make concurrency mode explicit and test parallel safety per upstream |
| Broker becomes a security boundary by implication | Misleading product claims | Keep loopback-only scope and describe audit metadata as observability, not compliance |
| Scope expands toward a generic API gateway | Crowded market and lost focus | Keep OpenAI, Anthropic, Kubernetes, portal, and enterprise IAM out of scope |

## Open questions resolved during implementation

- Which MCP SDK version passes the Phase 0 transport matrix?
- Which two real, expensive stdio upstreams are safe and useful to share?
- Which clients can consume Streamable HTTP directly at implementation time?
- What measured improvement is large enough for the operator to keep the broker enabled?

These questions are experimental gates, not invitations to add fallback machinery before evidence exists.

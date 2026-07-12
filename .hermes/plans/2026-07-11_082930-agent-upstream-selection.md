# Agent-Selected MCP Upstreams Implementation Plan

> Amended 2026-07-11 after the original implementation shipped. Phases 1–6 are historical and correspond to commits `6464887` through `9260c51`; Phase 7 is the open follow-up from the post-implementation audit.

## Goal

Let each downstream MCP agent explicitly select which Irigate upstreams or exact namespaced tools it wants, so Irigate does not qualify or start unrelated stdio MCP servers. Support positive and reverse upstream selectors with deterministic set semantics, while keeping exact tool selection as the recommended least-privilege mode.

## Progress

| Phase | Status | Checkpoint |
| --- | --- | --- |
| 1. Define and test selector parsing | Done | Committed checkpoint |
| 2. Carry selection through Streamable HTTP requests | Done | Committed checkpoint |
| 3. Defer upstream activation and filter tool exposure | Done | Committed checkpoint |
| 4. Make reload selection-aware | Done | Committed checkpoint |
| 5. Update user and implementation documentation | Done | Committed checkpoint |
| 6. Full verification and graph review | Done | Done as originally scoped; suite green at 129 tests; audit identified Phase 7 hardening gaps |
| 7. Harden session and reload boundaries | Not started | Pending |

## Current implemented context and assumptions

- Irigate exposes one stateful Streamable HTTP endpoint at `/mcp`.
- `app.create_app()` creates one process-wide `Broker` and one `StreamableHTTPSessionManager`.
- `Broker.start()` now initializes lifecycle and reporting state without starting configured upstreams; qualification, discovery, and process startup are deferred until selection requires an upstream.
- Tool schemas are discovered only by starting an upstream and issuing upstream `tools/list`; Irigate has no static tool manifest.
- Upstream processes may still be shared across compatible downstream sessions after qualification. Selection limits exposure and activation; it does not create a separate broker per agent.
- The selector is carried in the configured MCP URL, so every request made by that client includes it. No MCP protocol extension or client-specific initialization capability is required.
- Selector values contain routing names only. Credentials remain prohibited in URLs.
- Selection is optional. A client that omits it receives all configured upstreams; a client that narrows exposure provides one selector.
- Named groups such as `@development` are out of scope. They would require another configuration contract and are not needed for deterministic positive/reverse selection.

## Proposed endpoint contract

### Exact tool selection — recommended

```text
http://127.0.0.1:8765/mcp?tools=context7__resolve-library-id,context7__query-docs
```

- `tools` contains comma-separated exact `<upstream-key>__<tool-name>` values.
- Irigate starts only the upstreams referenced by those names.
- After discovering an upstream’s schemas, Irigate exposes only the requested tools.
- Unknown upstream prefixes and unknown tool names fail the downstream request; they are never silently ignored.
- Exact tool selectors do not support `!`. Excluding one tool cannot avoid starting its upstream and is not the process-selection use case.

### Upstream selection

```text
http://127.0.0.1:8765/mcp?upstreams=context7,shadcn
```

- Positive names form the base set.
- Irigate starts and exposes all tools from the resulting upstream set.

### Reverse and mixed upstream selection

```text
http://127.0.0.1:8765/mcp?upstreams=!code-review-graph,!documentdb
http://127.0.0.1:8765/mcp?upstreams=context7,shadcn,!shadcn
```

Set rules:

1. If at least one positive selector exists, positives form the base set.
2. If no positive selector exists, all currently configured upstreams form the base set.
3. Every `!name` is subtracted from the base set; exclusion wins regardless of token order.
4. Therefore `context7,shadcn,!shadcn` selects only `context7`.
5. `%21name` is naturally equivalent to `!name` after URL decoding.
6. Unknown positive and negative names are errors, catching stale agent configuration.
7. Duplicate tokens are normalized.
8. An empty final set is rejected.

Reverse-only selection is convenient when an agent initializes selected MCP servers directly, but it is not least privilege: newly added profile upstreams become selected after reload. README documentation must state this prominently and recommend `tools=` for strict configurations.

### Request validation

- At most one of `tools` or `upstreams` is accepted. Omitting both selects all configured upstreams.
- Repeated selector parameters, both parameters together, empty values/tokens, malformed names, and unrelated query parameters are rejected with HTTP 400 before MCP dispatch.
- Selection is normalized into an immutable typed value. Runtime code must not pass raw query strings or untyped mappings.
- The same normalized selection must be used for `tools/list` and `tools/call` on every request.
- A call outside the request’s selection is rejected even if another connected agent already activated that upstream or tool.

## Implemented architectural approach

The key change was deferred, selection-aware activation. Merely filtering `Broker.tools` would have been insufficient because the pre-feature `Broker.start()` spawned every upstream. Phases 1–6 implemented the following structure:

1. `selection.py` parses each request into a typed `ToolSelection` or `UpstreamSelection`, validates configured upstream keys, computes selected keys, and filters discovered tools.
2. The Streamable HTTP ASGI adapter validates the query and stores the normalized selection in a request-local `ContextVar` while `StreamableHTTPSessionManager.handle_request()` runs.
3. MCP `list_tools` and `call_tool` handlers read the current request selection and call selection-aware broker APIs.
4. Broker startup initializes state and reporting only. Qualification, schema discovery, and worker creation are deferred until a selected upstream is first needed.
5. Discovered schemas and qualification state are cached per upstream process-wide. Concurrent first activation is single-flight under an upstream-specific lock.
6. An admitted shared worker may be reused by multiple selected sessions; isolated workers remain keyed by downstream session.
7. Request selection is enforced before dispatch, independently of the process-wide schema cache.
8. Reload retires removed upstreams, prepares and atomically swaps changed active upstreams, and leaves added or changed dormant upstreams stopped until selection requires them.

## Step-by-step implementation plan

### Phase 1 — Define and test selector parsing

Objective: establish the complete URL contract without changing process lifecycle.

Files:

- Create `src/irigate/selection.py`.
- Create `tests/test_selection.py`.
- Update `src/irigate/AGENTS.md` after implementation because package ownership and routing contracts change.
- Update `tests/AGENTS.md` after implementation because selection tests become a durable behavioral contract.

Steps:

1. Write failing unit tests for exact `tools=` parsing, positive `upstreams=`, reverse-only upstream selection, and mixed positive/reverse selection.
2. Add tests proving exclusion wins independently of ordering and duplicates are normalized.
3. Add invalid-input tests for missing selector, both selector modes, repeated parameters, empty values/tokens, malformed names, tool-level `!`, unknown positive names, unknown exclusions, unsupported query parameters, and an empty resulting set.
4. Implement immutable typed selector models and one parser that accepts decoded query parameters plus configured upstream keys.
5. Keep tool syntax validation structural at parse time; validate exact tool existence only after the relevant upstream schema is discovered.
6. Run:

   ```bash
   uv run --frozen pytest -q tests/test_selection.py
   ```

   Expected: all selector tests pass.

Commit checkpoint:

- One coherent feature batch containing the parser, parser tests, and mechanically coupled DOX ownership updates.
- Suggested subject: `feat(selection): validate agent MCP selectors`

### Phase 2 — Carry selection through Streamable HTTP requests

Objective: make every MCP operation execute with a validated request-local selector.

Current boundary: transport validation and request-local propagation are complete. Selection-aware broker listing and dispatch remain in Phase 3 because those broker APIs are introduced with deferred activation. First-party compatibility and benchmark clients now send exact selectors so this breaking endpoint contract does not leave repository harnesses unusable.

Files:

- Modify `src/irigate/app.py`.
- Modify `tests/test_transport.py`.
- Modify `tests/helpers.py` if the broker URL helper needs an explicit selector argument.

Steps:

1. Add failing transport tests showing a bare `/mcp` URL selects all configured upstreams and starts no upstream until `tools/list` or `tools/call` needs it.
2. Add transport tests for `tools=...`, positive upstream selection, reverse-only selection, mixed selection, `%21` decoding, both selector modes, repeated selectors, and unrelated query parameters.
3. Introduce a request-local `ContextVar` whose value is the normalized selection.
4. Extend `_StreamableHTTPApp` to parse and validate each HTTP request query before delegating to `StreamableHTTPSessionManager`.
5. Return a bounded, credential-free HTTP 400 error for invalid selectors. Error text may contain upstream/tool names but not request headers or the full URL.
6. Update the MCP handlers to require the current normalized selection and pass it to broker list/call APIs.
7. Keep selected test URLs explicit and add transport coverage proving that a bare URL exposes all configured upstreams.
8. Run:

   ```bash
   uv run --frozen pytest -q tests/test_selection.py tests/test_transport.py
   ```

   Expected: selector and downstream transport tests pass.

Commit checkpoint:

- Suggested subject: `feat(transport): require agent MCP selection`

### Phase 3 — Defer upstream activation and filter tool exposure

Objective: prove that unselected upstreams are never qualified or started.

Files:

- Modify `src/irigate/broker.py`.
- Potentially modify `src/irigate/upstream.py` only if a dedicated discovery lifecycle is needed; prefer keeping process ownership unchanged.
- Modify `tests/test_broker.py`.
- Modify `tests/test_routing.py`.
- Modify `tests/test_isolation.py` and `tests/test_qualification.py` where current setup assumes eager startup.
- Extend `tests/helpers.py` with explicit process-start evidence if existing fixtures do not expose it.

Steps:

1. Write failing broker tests with at least two upstream fixtures proving that selecting one does not start, qualify, discover, or report a spawn for the other.
2. Add a concurrent-first-use test proving two agents selecting the same upstream produce one discovery/qualification activation path rather than duplicate startup.
3. Add exact-tool tests proving only requested schemas appear in `tools/list`, unrequested calls fail, and an unknown exact tool fails after only its named upstream is discovered.
4. Add upstream-mode tests proving all tools from selected upstreams appear and excluded upstreams cannot be called even when another agent activated them.
5. Refactor `Broker.start()` into lifecycle initialization only; remove its loop over all configured upstreams.
6. Add a selection-aware `list_tools(selection)` API that activates only selected upstreams, caches their schemas, and returns a filtered copy.
7. Add per-upstream activation locks or task caching. Do not serialize unrelated upstream activation behind the existing global worker lock.
8. Change `call_tool` to accept the normalized selection, enforce it first, activate the selected upstream if necessary, and then use existing exact routing.
9. Preserve qualification behavior and `--require-qualified-sharing`, but apply it when a shareable upstream is first selected. A selected upstream that fails strict qualification fails that request without stopping unrelated active upstreams.
10. Ensure a failed activation leaves no partial schema, qualification, shared worker, or live child process in broker state.
11. Update tests that called `Broker.start()` and expected eager tools so they explicitly call selection-aware listing or dispatch.
12. Run focused tests:

    ```bash
    uv run --frozen pytest -q \
      tests/test_broker.py \
      tests/test_routing.py \
      tests/test_isolation.py \
      tests/test_qualification.py \
      tests/test_shutdown.py
    ```

    Expected: all focused lifecycle, routing, isolation, qualification, and shutdown tests pass with no orphan processes.

Commit checkpoint:

- Suggested subject: `feat(broker): activate only selected MCP upstreams`

### Phase 4 — Make reload selection-aware

Objective: retain atomic reload behavior without waking dormant upstreams.

Files:

- Modify `src/irigate/broker.py`.
- Modify `tests/test_reload.py`.
- Modify `tests/test_runtime_report.py` if dormant-upstream metrics require explicit assertions.

Steps:

1. Add a failing test proving an added but never-selected upstream remains dormant after reload.
2. Add a failing test proving a changed activated upstream is prepared and swapped without disconnecting its selected client.
3. Add a failing test proving a changed dormant upstream is not started until a later selection.
4. Add a reverse-only test proving a newly added upstream is part of the client’s recomputed selection and starts only when that client next requests `tools/list` or calls one of its tools.
5. Add tests proving removed/excluded upstreams disappear from listing and cannot be dispatched through stale process-wide schema caches.
6. Track activation state separately from configured state. During reload, prepare only changed keys that are currently activated; remove cached state and retire workers for removed keys.
7. Recompute every request’s selection against the current configuration. This makes unknown exclusions fail after a profile removes the excluded upstream, as required by the stale-configuration rule.
8. Keep host/port rejection and failed-reload fallback unchanged.
9. Run:

   ```bash
   uv run --frozen pytest -q tests/test_reload.py tests/test_runtime_report.py
   ```

   Expected: reload and reporting tests pass; dormant upstream spawn counts remain zero.

Commit checkpoint:

- Suggested subject: `feat(reload): preserve dormant upstream selection`

### Phase 5 — Update user and implementation documentation

Objective: make agent configuration, safety tradeoffs, and runtime behavior operationally clear.

Files:

- Modify `README.md`.
- Modify `IMPLEMENTATION.md`.
- Modify root `AGENTS.md` only if the final behavior changes a project-wide architectural decision.
- Modify `src/irigate/AGENTS.md` and `tests/AGENTS.md` if not already updated with their owning feature phases.

README changes:

1. Add “Agent-side selection” to the feature overview.
2. Replace the bare `/mcp` client URL in “Run” with explicit examples for:
   - exact least-privilege tools;
   - positive upstream selection;
   - reverse-only selection for an MCP started directly by the agent;
   - mixed positive/reverse selection and exclusion-wins semantics.
3. Include a concrete agent configuration showing Irigate alongside a directly initialized `code-review-graph` server.
4. Document that selectors are optional, omission exposes all configured upstreams, and selected requests use only one mode.
5. Add a compact validation table covering invalid combinations and unknown names.
6. Warn that reverse-only selection automatically admits newly configured upstreams after reload; recommend `tools=` when least privilege matters.
7. Correct startup wording: Irigate no longer starts all configured upstreams at broker launch; selected upstreams activate on demand.

IMPLEMENTATION.md changes:

1. Update runtime architecture to describe request-local selection and deferred activation.
2. Add the selector grammar and set semantics to the routing contract.
3. Document per-request authorization-like enforcement: a process-wide activated upstream is not automatically exposed to another agent.
4. Update reload, qualification, shutdown, runtime-report, and extension contracts for dormant upstreams.
5. Add verification requirements proving unselected processes are not started.

DOX closeout:

1. Re-read the root, `src`, `src/irigate`, and `tests` AGENTS.md chain.
2. Update ownership and local contracts for selection parsing, deferred activation, and selection-aware tests.
3. Keep Child DOX indexes current.
4. If the root architectural decisions already cover the behavior through the local-broker boundary, leave root `AGENTS.md` unchanged and state that explicitly in closeout.

Documentation verification:

```bash
uv run --frozen python -m irigate --config profiles/mvp.yaml --check
```

Expected: profile validation succeeds without starting upstream processes.

Commit checkpoint:

- Documentation is mechanically coupled to the public feature and may be included with the final feature batch if implementation and docs land together. If implementation phases are committed independently, use a separate coherent documentation batch.
- Suggested separate subject: `docs(readme): document agent MCP selection`

### Phase 6 — Full verification and graph review

Objective: verify behavior, process cleanup, documentation consistency, and blast radius.

This was the original final verification gate. Its recorded evidence remains valid for Phases 1–6; Phase 7 adds the hardening gates discovered by the post-implementation audit.

Steps:

1. Run the complete suite:

   ```bash
   uv run --frozen pytest -q
   ```

   Expected: all tests pass.

2. Run both static profile checks:

   ```bash
   uv run --frozen python -m irigate --config profiles/mvp.yaml --check
   uv run --frozen python -m irigate --config profiles/benchmark-heavy.yaml --check
   ```

   Expected: both checks succeed and start no upstream processes.

3. Run the compatibility harness with explicit selectors if its client URL construction is affected:

   ```bash
   uv run --frozen python scripts/compatibility.py --config profiles/mvp.yaml
   ```

   Expected: compatibility checks pass without orphan processes. If credentials or network access are unavailable, report this gate as blocked rather than fabricating evidence.

4. Build/update the code-review graph and run change detection plus affected-flow analysis against the actual changed files.
5. Inspect `git diff --stat -- <file>` for every modified path and split any unrelated or disproportionately large pre-existing diff before staging.
6. Perform the mandatory DOX pass and confirm intentionally unchanged docs.
7. Verify final repository state with:

   ```bash
   git status --short --branch
   git diff --check
   ```

8. Do not commit unless explicitly requested. If commits are requested, present coherent batches for approval first and use the repository’s configured Irigate author identity.

### Phase 7 — Harden session and reload boundaries

Objective: close the post-implementation audit gaps around stateful-session consistency, activation/reload races, and missing end-to-end evidence before treating the feature as complete.

Files:

- Modify `src/irigate/app.py`.
- Modify `src/irigate/broker.py`.
- Modify `tests/test_broker.py` for broker-level activation failure and lifecycle cases.
- Modify `tests/test_transport.py`.
- Modify `tests/test_reload.py`.
- Modify `tests/test_runtime_report.py` if dormant-state reporting needs correction rather than test coverage only.
- Modify `tests/helpers.py` only if the existing `running_broker` helper, which currently yields one selected URL string, is insufficient for constructing multiple selector URLs. Prefer extending it to expose a base URL or URL-builder while preserving existing callers rather than creating another server fixture.
- Update `src/irigate/AGENTS.md` and `tests/AGENTS.md` only if implementation changes their durable contracts.

#### 7.1 — Bind selection to the stateful MCP session

1. Inspect the installed MCP library to identify the stable session identifier and lifecycle boundary available before `list_tools` and `call_tool` dispatch. Do not assume Python object identity is stable across HTTP requests without proving it in a focused test.
2. Treat this inspection as a bounded spike: prove identity stability across requests and identify a teardown hook before choosing storage. If the SDK exposes neither, stop and revise this subsection rather than adding polling, an unbounded registry, or an identity inferred from client address or headers.
3. Bind the first request's normalized selection, including the default-all selection from a bare URL, to that downstream MCP session. A client that needs a different `tools=` or `upstreams=` selection must open a new MCP session.
4. Reject every later request that carries a different normalized selection for the same session before broker listing or dispatch. Return a generic, credential-free mismatch error that does not echo the full URL, query string, or selector values, and leave unrelated sessions running.
5. Keep `agent` as per-request attribution metadata rather than session-bound state. It is not authorization, and changing it must not alter the bound selector.
6. Remove the binding when the session ends. Prefer an MCP lifecycle hook or manager-owned session state; do not add polling, periodic cleanup, or an unbounded process-wide map.
7. Add transport tests proving:
   - initialization with `tools=echo__repeat` cannot later broaden to `upstreams=echo` in the same session;
   - a client that changes from one valid `tools=` allowlist to another in the same session receives the generic selector-mismatch error;
   - initialization on the bare endpoint cannot later narrow or otherwise change selection in the same session;
   - rejection does not terminate or alter another session;
   - changing only `agent=` within one session does not alter or bypass the bound selector.

Acceptance criteria:

- Selection is immutable after a stateful MCP session is established.
- Session tracking has an explicit lifecycle and cannot grow without bound.
- Selector mismatch never reaches `Broker.list_tools()` or `Broker.call_tool()`.
- Invalid selector syntax remains an HTTP 400 carrying the existing safe `SelectionError`; a valid selector that differs from the session-bound selector returns a separate generic mismatch error that echoes no selector values.

#### 7.2 — Serialize activation with changed and removed upstream reloads

Blocking scope: complete 7.2a and 7.2b before treating the audited race as closed. Then complete the additional lifecycle hardening in 7.2c before closing Phase 7.

##### 7.2a — Prevent stale activation publication

1. Add deterministic race tests using `asyncio.Event` barriers rather than timing sleeps. Pause activation after it captures the old upstream definition, then concurrently:
   - reload a changed definition for the same key;
   - reload a profile that removes the key.
2. Define one deadlock-free lock ordering for reload, per-key activation, and worker mutation. Do not document an ordering until the implementation and tests prove it.
3. Make reload wait for, cancel, or invalidate in-flight activation for changed and removed keys. The activation path must verify that the configuration generation or exact upstream definition it prepared is still current before publishing schemas, qualification state, metrics, or workers.
4. Close every stale prepared worker and discard its schemas and qualification result.
5. Add bounded-timeout assertions proving these race tests complete without deadlock and only the replacement configuration can become visible after reload.

##### 7.2b — Preserve in-flight call semantics

1. Add deterministic tests for a tool call already executing when reload changes or removes its upstream. Cover a shareable worker serving multiple downstream sessions, not only one isolated binding.
2. Prove each admitted call either completes on its worker or fails boundedly under the documented shutdown policy; reload must not strand callers or leak the retired worker.
3. Add bounded-timeout assertions for every in-flight-call test.

##### 7.2c — Additional lifecycle hardening

1. Cover a slow or blocked discovery while reload changes or removes the same key. Reload must cancel or invalidate it within a bounded time rather than waiting indefinitely on its activation lock.
2. Prune activation locks for removed keys after no activation can still publish through them. Repeated add/activate/remove cycles must not grow `_activation_locks` without bound.
3. Define and test multi-upstream partial failure semantics. Recommended default: activation already completed for an earlier selected upstream remains cached when a later selected upstream fails; the request fails, no partial tool list is returned, and the failed upstream leaves no worker, schema, or qualification residue.

Acceptance criteria:

- A stale activation result cannot publish after a changed or removed upstream reload.
- Changed and removed keys leave no stale worker, schema, qualification, or live-instance count.
- An in-flight call has deterministic completion or bounded failure semantics during changed or removed upstream reload.
- Slow discovery cannot block reload indefinitely, and removed-key activation locks do not accumulate.
- Multi-upstream activation failure has explicit, tested partial-success semantics and never returns a partial tool list.
- Activations for unrelated keys remain independent.

#### 7.3 — Add missing transport and reload evidence

1. Add a real Streamable HTTP test for `tools=echo__repeat` proving `tools/list` exposes only `echo__repeat`, hides another tool from the same upstream, and does not activate another configured upstream.
2. Through the same HTTP boundary, call an unselected tool from the already activated upstream and prove selection enforcement rejects it.
3. Open two sessions with different selectors and run `tools/list` concurrently with `asyncio.gather`; prove the request-local `ContextVar` does not leak selection across sessions.
4. Add a reverse-only reload test that parses `upstreams=!echo`, adds a new upstream, re-evaluates the selector against the live configuration, and proves the new upstream is admitted only on the next list or call. Assert it remains dormant immediately after reload.
5. Add runtime-report coverage for a configured but dormant shareable upstream: zero spawns and live instances, `qualification: not_requested`, stopped activity, and no reporting that implies successful qualification or sharing admission.
6. Reconcile `IMPLEMENTATION.md` and the nearest owning AGENTS.md files with the final session-binding, reload synchronization, in-flight-call, and notification contracts. Update the website copy only if public behavior or operator guidance changes.
7. Add operator guidance that changing `tools=` or `upstreams=` requires opening a new MCP session; changing only `agent=` remains allowed because it is attribution metadata. Apply this to README and website documentation where selected client URLs are documented.

Acceptance criteria:

- Exact tool filtering and rejected dispatch are proven over HTTP, not only through broker unit tests.
- Concurrent sessions retain independent selections.
- Reverse-only broadening and dormant reporting match the documented contracts.

#### 7.4 — Freeze notification safety

Priority: lower than 7.1–7.3 because the current implementation emits no tool-list-changed notifications. This subsection freezes that safe behavior and must not block the earlier correctness fixes if the installed client exposes no stable notification-observation API.

1. Record beside the MCP `list_tools` handler that process-wide `notifications/tools/list_changed` must not be introduced while sessions expose different selected subsets. Any future notification must be scoped to the receiving session's current selection.
2. Add a transport test in which one session activates another upstream while a differently selected session remains connected; prove the first session receives no process-wide tool-list-changed notification. If the MCP library supports only process-wide notifications, the release behavior is to emit none, and the test must assert that explicitly. Use a short bounded timeout and the MCP client's supported notification interface rather than reading private queues.
3. If the installed MCP client offers no stable public way to observe notifications, retain the explicit source contract and document the blocked test instead of coupling tests to library internals.

Acceptance criteria:

- Activation by one session cannot leak a broader tool surface to another through notifications.
- The limitation and its future extension boundary are explicit in production code.

#### Phase 7 verification

Run focused tests first:

```bash
uv run --frozen pytest -q \
  tests/test_broker.py \
  tests/test_isolation.py \
  tests/test_shutdown.py \
  tests/test_transport.py \
  tests/test_reload.py \
  tests/test_runtime_report.py
```

Then run the complete suite and static checks:

```bash
uv run --frozen pytest -q
uv run --frozen python -m irigate --config profiles/mvp.yaml --check
uv run --frozen python -m irigate --config profiles/benchmark-heavy.yaml --check
git diff --check
```

Expected: all tests and checks pass, race tests complete within their bounds, and no child process remains.

Commit checkpoint:

- Keep session binding and activation/reload synchronization in separate coherent commits unless their implementation is mechanically inseparable.
- Put transport/reporting evidence with the behavior it protects; do not create a tests-only cleanup commit detached from its production contract.

## Files likely to change

| Path | Responsibility |
| --- | --- |
| `src/irigate/selection.py` | Typed selector grammar, normalization, validation, and set computation. |
| `src/irigate/app.py` | Query validation, request-local propagation, and stateful-session selector binding and cleanup. |
| `src/irigate/broker.py` | Deferred activation, schema filtering, selection enforcement, and activation/reload synchronization. |
| `src/irigate/upstream.py` | Only if discovery lifecycle needs a minimal worker API adjustment. |
| `tests/test_selection.py` | Pure selector contract. |
| `tests/test_transport.py` | HTTP selector requirement and decoding. |
| `tests/test_broker.py` | Dormant startup and activation behavior. |
| `tests/test_routing.py` | Selection-scoped listing and dispatch. |
| `tests/test_reload.py` | Selection-aware dormant/active reload behavior. |
| `tests/test_qualification.py` | Deferred qualification and strict failure behavior. |
| `tests/test_isolation.py` | Selection must not weaken isolated worker scoping. |
| `tests/test_shutdown.py` | Activated-only cleanup and orphan prevention. |
| `tests/test_runtime_report.py` | Zero-spawn evidence for dormant upstreams. |
| `tests/helpers.py` | Explicit selected URLs and process evidence helpers. |
| `README.md` | Agent configuration and selector usage. |
| `IMPLEMENTATION.md` | Runtime, routing, reload, and verification contracts. |
| `src/irigate/AGENTS.md` | Package ownership and deferred-activation contract. |
| `tests/AGENTS.md` | Selection test ownership. |

## Tests and acceptance criteria

The implementation is complete only when all of the following are proven:

- A request without a selector exposes all configured upstreams; a request with both selector modes fails before MCP dispatch.
- Exact `tools=` starts only referenced upstreams and exposes only requested tools.
- Positive `upstreams=` starts only the named upstreams.
- Reverse-only selection starts all configured upstreams except exclusions.
- Mixed upstream selection uses positive-base-minus-exclusions semantics.
- Exclusion wins independently of token order.
- Unknown positive names, unknown exclusions, malformed names, and empty final selections fail explicitly.
- A tool or upstream excluded for one agent remains inaccessible to that agent even when another agent activated it.
- Concurrent first selection does not duplicate discovery or qualification startup.
- Dormant upstreams have zero spawns and are not qualified.
- Added dormant upstreams remain dormant on reload.
- Changed active upstreams retain atomic replacement and downstream connection preservation.
- Reverse-only clients include newly configured upstreams only after re-evaluation, with the documented broadening risk.
- Shutdown leaves no child process behind.
- Audit and runtime reports remain metadata-only and do not record full URLs or query strings.
- README and IMPLEMENTATION examples match executable behavior.
- A stateful MCP session cannot change its normalized selection after initialization or first binding.
- Concurrent sessions with different selectors remain isolated under interleaved requests.
- Reload cannot publish an activation result prepared from a changed or removed upstream definition.
- Active calls from multiple sessions sharing one worker have deterministic completion or bounded failure semantics during reload.
- Dormant shareable upstream reports retain zero process evidence and do not imply qualification or sharing admission.
- Process-wide tool-list-changed notifications do not leak another session's broader tool surface.

## Risks and tradeoffs

- **Stateful HTTP session consistency:** selection comes from each request URL rather than being stored in MCP initialization capabilities. The app must reject attempts to change selectors within one MCP session, or prove the Streamable HTTP manager always receives the same configured URL. Prefer explicitly binding the normalized selector to the MCP session ID on initialization/first request and rejecting later mismatch.
- **Compatibility:** session-bound selection intentionally rejects clients that currently change `tools=` or `upstreams=` while reusing one MCP session. Do not add a compatibility fallback; clients must open a new session to change selection. Changing only `agent=` remains permitted because it is request attribution, not authorization.
- **Activation races:** process-wide cache reuse can create duplicate upstreams without per-key single-flight synchronization. Avoid one global lock because unrelated upstreams should initialize independently.
- **Strict qualification timing:** `--require-qualified-sharing` moves from process startup to first selection. README and CLI wording must stop promising that all shareable upstreams are validated before the listener opens.
- **Reverse-selection broadening:** a profile reload can make a new upstream eligible. This is intentional but must be clearly documented; exact tools remain the least-privilege recommendation.
- **Unknown reverse selectors after removal:** failing a previously valid client when its excluded upstream disappears catches stale configuration but may surprise operators. Keep this fail-closed rule because it was explicitly requested.
- **Tool discovery cost:** exact tool mode still has to start each referenced upstream once to validate and obtain its schema. It avoids unrelated upstreams, not startup of the selected upstream.
- **Process-wide metrics:** configured-but-dormant upstreams should remain visible with zero spawns, but runtime reporting must not imply qualification or effective shared/isolated mode before activation.
- **MCP notifications:** if Irigate emits tool-list-changed notifications, they must be scoped carefully because different sessions expose different subsets. If the current MCP library only supports process-wide notifications, omit new notification behavior rather than leaking a broader list.

## Resolved decisions and remaining decisions

Item 4 is the only unresolved design decision and is the entry gate for Phase 7.1.

1. Invalid query selectors return a bounded HTTP 400 through `_StreamableHTTPApp` before MCP dispatch. The response contains only the safe selection error.
2. Strict first-use qualification failure raises `BrokerInitializationError` for that list or call path and must leave unrelated sessions and upstreams running.
3. First-party compatibility and benchmark clients use explicit selectors matching their scenarios; the bare endpoint remains the intentional default-all contract.
4. `Server.request_context.session` currently supplies the worker-binding key during tool calls, but its suitability as a stable cross-request selector-binding identity and its cleanup lifecycle remain unproven. Phase 7.1 must resolve this from the installed MCP implementation and a focused transport test before choosing storage, then replace this item with the chosen identity, storage ownership, and teardown decision.
5. `agent=` remains per-request attribution metadata and is not part of the bound selector. Changing only `agent=` within one session must neither trigger selector mismatch nor alter selection enforcement.

## Post-implementation audit record

The 2026-07-11 audit compared the shipped implementation and tests with this plan and found three gaps: selector changes were not rejected within an existing stateful MCP session; deferred activation was not synchronized with changed or removed upstream reloads; and Phase 2 retained a stale bare-URL HTTP 400 instruction that contradicted the implemented default-all contract. Phase 7 preserves the first two as open hardening work. Phase 2 now reflects the shipped bare-URL behavior.

No named selector groups, wildcard syntax, persistent schema cache, dynamic configuration API, or MCP protocol extension should be added in this feature.

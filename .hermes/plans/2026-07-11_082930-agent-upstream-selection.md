# Agent-Selected MCP Upstreams Implementation Plan

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
| 6. Full verification and graph review | Todo | Requires Phase 5 commit |

## Current context and assumptions

- Irigate exposes one stateful Streamable HTTP endpoint at `/mcp`.
- `app.create_app()` creates one process-wide `Broker` and one `StreamableHTTPSessionManager`.
- `Broker.start()` currently qualifies and starts every configured upstream before the HTTP endpoint begins serving.
- Tool schemas are discovered only by starting an upstream and issuing upstream `tools/list`; Irigate has no static tool manifest.
- Upstream processes may still be shared across compatible downstream sessions after qualification. Selection limits exposure and activation; it does not create a separate broker per agent.
- The selector is carried in the configured MCP URL, so every request made by that client includes it. No MCP protocol extension or client-specific initialization capability is required.
- Selector values contain routing names only. Credentials remain prohibited in URLs.
- This is an intentionally breaking endpoint contract: a client must provide exactly one selector. There is no implicit “all upstreams” compatibility mode.
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

- Exactly one of `tools` or `upstreams` is required.
- Repeated selector parameters, both parameters together, empty values/tokens, malformed names, and unrelated query parameters are rejected with HTTP 400 before MCP dispatch.
- Selection is normalized into an immutable typed value. Runtime code must not pass raw query strings or untyped mappings.
- The same normalized selection must be used for `tools/list` and `tools/call` on every request.
- A call outside the request’s selection is rejected even if another connected agent already activated that upstream or tool.

## Architectural approach

The key change is deferred, selection-aware activation. Merely filtering `Broker.tools` is insufficient because the current `Broker.start()` has already spawned every upstream.

1. Add a small selection module that parses one request query into a typed `ToolSelection` or `UpstreamSelection`, validates it against configured upstream keys, computes selected upstream keys, and filters discovered tools.
2. Wrap the Streamable HTTP endpoint with an ASGI adapter that validates the query and stores the normalized selection in a request-local `ContextVar` while `StreamableHTTPSessionManager.handle_request()` runs.
3. Change the MCP `list_tools` and `call_tool` handlers to read the current request selection and call selection-aware broker APIs.
4. Change broker startup to initialize broker state and reporting only. Defer qualification, schema discovery, and worker creation until a selected upstream is first needed.
5. Cache discovered schemas and qualification state per upstream process-wide. Concurrent first activation of the same upstream must be single-flight under an upstream-specific lock so two agents do not spawn duplicate discovery workers.
6. Preserve existing sharing semantics: an admitted shared worker may be reused by multiple selected sessions; isolated workers remain keyed by downstream session.
7. Enforce the request selection before dispatch, independently of the broker’s process-wide schema cache.
8. Make reload selection-aware. Removed upstreams are retired. Changed upstreams that have previously been activated are prepared and swapped atomically. Never-activated added or changed upstreams remain dormant until selected. Existing reverse-only clients see newly added upstreams on their next `tools/list`, at which point activation occurs.

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

1. Add failing transport tests showing `/mcp` without a selector returns HTTP 400 and never starts an upstream.
2. Add transport tests for `tools=...`, positive upstream selection, reverse-only selection, mixed selection, `%21` decoding, both selector modes, repeated selectors, and unrelated query parameters.
3. Introduce a request-local `ContextVar` whose value is the normalized selection.
4. Extend `_StreamableHTTPApp` to parse and validate each HTTP request query before delegating to `StreamableHTTPSessionManager`.
5. Return a bounded, credential-free HTTP 400 error for invalid selectors. Error text may contain upstream/tool names but not request headers or the full URL.
6. Update the MCP handlers to require the current normalized selection and pass it to broker list/call APIs.
7. Update existing test helpers and transport tests to use an explicit selector; do not add an implicit test default that hides the new production requirement.
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
4. Document that exactly one selector is mandatory and that no implicit-all compatibility path exists.
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

## Files likely to change

| Path | Responsibility |
| --- | --- |
| `src/irigate/selection.py` | Typed selector grammar, normalization, validation, and set computation. |
| `src/irigate/app.py` | Query validation and request-local selector propagation. |
| `src/irigate/broker.py` | Deferred activation, schema filtering, selection enforcement, and reload behavior. |
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

- A request without exactly one selector fails before MCP dispatch.
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

## Risks and tradeoffs

- **Stateful HTTP session consistency:** selection comes from each request URL rather than being stored in MCP initialization capabilities. The app must reject attempts to change selectors within one MCP session, or prove the Streamable HTTP manager always receives the same configured URL. Prefer explicitly binding the normalized selector to the MCP session ID on initialization/first request and rejecting later mismatch.
- **Activation races:** process-wide cache reuse can create duplicate upstreams without per-key single-flight synchronization. Avoid one global lock because unrelated upstreams should initialize independently.
- **Strict qualification timing:** `--require-qualified-sharing` moves from process startup to first selection. README and CLI wording must stop promising that all shareable upstreams are validated before the listener opens.
- **Reverse-selection broadening:** a profile reload can make a new upstream eligible. This is intentional but must be clearly documented; exact tools remain the least-privilege recommendation.
- **Unknown reverse selectors after removal:** failing a previously valid client when its excluded upstream disappears catches stale configuration but may surprise operators. Keep this fail-closed rule because it was explicitly requested.
- **Tool discovery cost:** exact tool mode still has to start each referenced upstream once to validate and obtain its schema. It avoids unrelated upstreams, not startup of the selected upstream.
- **Process-wide metrics:** configured-but-dormant upstreams should remain visible with zero spawns, but runtime reporting must not imply qualification or effective shared/isolated mode before activation.
- **MCP notifications:** if Irigate emits tool-list-changed notifications, they must be scoped carefully because different sessions expose different subsets. If the current MCP library only supports process-wide notifications, omit new notification behavior rather than leaking a broader list.

## Open implementation questions

These should be resolved by source inspection or a focused test during implementation, not by expanding product scope:

1. Does `Server.request_context` expose a stable downstream MCP session ID during `list_tools`, `call_tool`, and initialization handling that can bind the selector against later request changes?
2. Can Starlette/`StreamableHTTPSessionManager` return a clean HTTP 400 before creating session state, or is a small ASGI response helper needed?
3. Should strict qualification failure be represented as an MCP error from `tools/list` or terminate only that downstream session? The preferred behavior is a bounded MCP request failure that leaves unrelated sessions and upstreams running.
4. Does the compatibility harness hardcode `/mcp`, and if so, which explicit selector best matches each scenario?

No named selector groups, wildcard syntax, persistent schema cache, dynamic configuration API, or MCP protocol extension should be added in this feature.

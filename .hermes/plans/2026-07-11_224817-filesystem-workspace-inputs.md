# Filesystem Workspace Inputs Implementation Plan

## Goal

Add explicit per-session upstream inputs so a client can select only the filesystem upstream and bind its isolated MCP process to a validated workspace:

`/mcp?upstreams=filesystem&filesystem.workspace=/absolute/project/path`

Extend `allowed_roots` with path-segment glob semantics for `*` and `**` while preserving fail-closed path and process isolation.

## Approval gate

The user approved implementation. Approval authorizes code, tests, profile, and documentation changes but not commits or pushes.

## Progress

| Phase | Status | Checkpoint |
| --- | --- | --- |
| 1. Profile models and validation | Done | Committed checkpoint |
| 2. Canonical workspace matching | Done | Committed checkpoint |
| 3. Namespaced upstream inputs | Done | Committed checkpoint |
| 4. Streamable HTTP session binding | Done | Committed checkpoint |
| 5. Per-session arguments and workers | Todo | Requires Phase 4 commit checkpoint |
| 6. Profile and documentation | Todo | Requires Phase 5 commit checkpoint |
| 7. Verification and closeout | Todo | Requires Phase 6 commit checkpoint |

## Current context and assumptions

- `upstreams=filesystem` already narrows tool discovery and dispatch to the filesystem upstream.
- Unknown query parameters currently fail closed in `src/irigate/selection.py`.
- Upstream command arguments, process `cwd`, and environment are static profile values.
- Non-shareable workers are currently keyed by `(session_key, upstream_key)` and receive the broker-resolved static environment.
- The official filesystem MCP server receives allowed paths as command arguments, so `filesystem.workspace` is a declared upstream input mapped to an argument placeholder, not generic environment forwarding.
- The `agent` query value remains attribution only and must not authorize a workspace.
- Existing uncommitted changes in `profiles/benchmark-heavy.yaml` and `profiles/AGENTS.md` must be preserved. Do not touch the untracked `settings.json` or `profiles/.benchmark-heavy.yaml.swp` unless separately requested.

## Proposed contract

### Profile schema

Use a narrow workspace-specific schema rather than arbitrary client-controlled process environment variables:

```yaml
filesystem:
  transport: stdio
  command: npx
  args:
    - -y
    - "@modelcontextprotocol/server-filesystem"
    - "{workspace}"
  inputs:
    workspace:
      type: directory
      required: true
      allowed_roots:
        - /home/*/src
        - /srv/**/projects
```

Initial scope supports only the reserved `workspace` input with `type: directory` and the exact `{workspace}` argument placeholder. Generic input-to-environment mapping is deferred.

### Query semantics

- Accept `<upstream-key>.workspace=<absolute-path>` only when that upstream is explicitly and positively selected by `upstreams=` or required by an exact `tools=` selector.
- Do not let an input implicitly select an upstream.
- Reject inputs for reverse-only or bare-URL default-all selection because those forms do not explicitly grant dynamic configuration.
- Reject unknown upstream keys, unknown input names, duplicate values, empty values, and inputs for excluded upstreams.
- Require every selected upstream with a required workspace input to receive exactly one value.
- Bind validated inputs to the MCP Streamable HTTP session; query changes cannot mutate an existing session.

### `allowed_roots` semantics

Treat every entry as an absolute path pattern over complete path segments:

- Expand a leading `~` or `~/` to the broker process user's home directory. Reject `~user`, embedded `~`, and query-side tilde expansion.
- Expand profile-side `${ENV_NAME}` references from the broker process environment before validating the pattern. Accept only the braced form; reject `$NAME`, shell defaults, command substitution, and unset variables. Environment-derived values must resolve to absolute path material and must not introduce `*` or `**` segments.
- Expansion applies only to configured `allowed_roots`; `filesystem.workspace` query values remain explicit absolute paths and never expand environment variables or `~`.
- Literal segments match exactly.
- `*` matches exactly one non-empty path segment. This supports forms such as `/home/*/src` (the requested `/*/` behavior).
- `**` matches zero or more complete path segments. This supports forms such as `/srv/**/projects` and terminal `/**`.
- Wildcards are valid only when the entire segment is `*` or `**`; reject `proj*`, `***`, character classes, braces, and relative patterns.
- A matched pattern denotes an allowed root and implicitly permits all descendants. An explicit trailing `/**` is accepted and has the same descendant effect, so `/srv/projects` and `/srv/projects/**` both allow that subtree.
- Normalize the requested workspace with `Path.resolve(strict=True)` before matching. Match the canonical path, not the user-provided lexical path.
- Collapse every `.` and `..` segment through canonical resolution before authorization. A value such as `/srv/my/project/../../../what-ever` is checked as its resolved canonical destination and is rejected unless that destination independently matches an allowed root.
- Resolve literal non-wildcard prefixes in patterns and reject traversal, malformed paths, non-directory workspaces, and symlink escapes.
- Apply authorization to the canonical directory itself and require it to be equal to or below a matched root. Never authorize from the untrusted string prefix; `/srv/my/project-escape` must not match `/srv/my/project`.
- Matching is case-sensitive on Linux. No Windows path grammar is added in this phase.

Examples:

| Pattern | Workspace | Result |
|---|---|---|
| `/home/*/src` | `/home/raphael/src/project` | allow |
| `/home/*/src` | `/home/raphael/work/project` | reject |
| `/srv/**/projects` | `/srv/projects/app` | allow |
| `/srv/**/projects` | `/srv/teams/a/projects/app` | allow |
| `/srv/projects/**` | `/srv/projects` | allow |
| `/srv/projects/**` | `/srv/projects/a/b` | allow |
| `${HOME}/src/*` | `/home/raphael/src/project` | allow after profile expansion |
| `~/src` | `/home/raphael/src/project` | allow after profile expansion |
| `/srv/my/project` | `/srv/my/project/../../../what-ever` | reject after canonical resolution |

### Instance lifecycle

- Keep dynamically configured upstreams non-shareable; reject `shareable: true` plus `inputs` during profile validation.
- Carry an immutable validated input mapping in the selection/session context.
- Key isolated workers by `(session_key, upstream_key, input_fingerprint)`.
- Render `{workspace}` into a fresh argument tuple before spawning; never mutate the frozen profile object.
- Reuse the same worker only within the same downstream session and identical validated input set.
- Use the existing idle timeout and shutdown path for cleanup.
- Keep input values out of audit records and runtime reports; report only existing metadata and counts.

## Step-by-step implementation plan

### 1. Add profile models and fail-closed validation

Files:

- `src/irigate/models.py`
- `tests/test_config.py`
- `src/irigate/AGENTS.md`
- `tests/AGENTS.md`

Steps:

1. Add a frozen workspace input model with `type: Literal["directory"]`, `required`, and non-empty `allowed_roots`.
2. Add an `inputs` mapping to `UpstreamConfig`, initially allowing only the key `workspace`.
3. Expand only leading `~`/`~/` and braced `${ENV_NAME}` references in profile-side patterns, then validate absolute patterns and segment-only `*`/`**` syntax. Missing variables fail profile loading by name without exposing values.
4. Validate exactly one `{workspace}` placeholder when the workspace input is configured and reject the placeholder otherwise.
5. Reject dynamic inputs on `shareable: true` upstreams.
6. Add RED tests for valid literal, tilde, environment, `*`, and `**` patterns and every invalid schema combination; run `uv run --frozen pytest -q tests/test_config.py` to confirm failures.
7. Implement the minimal model validation and rerun the test file to green.

### 2. Implement canonical workspace matching as a pure unit

Files:

- `src/irigate/workspace.py` (new)
- `tests/test_workspace.py` (new)
- `src/irigate/AGENTS.md`
- `tests/AGENTS.md`

Steps:

1. Add table-driven RED tests covering literal roots, exact-one-segment `*`, zero-or-more-segment `**`, terminal `/**`, non-existing paths, files, `.`/`..` traversal, sibling-prefix confusion, and final/intermediate symlink escapes.
2. Implement a segment matcher without shell expansion or filesystem glob enumeration.
3. Resolve the candidate strictly, verify it is a directory, and compare canonical path segments against validated patterns with implicit descendant allowance.
4. Ensure errors identify only the rejected field/path and do not expose environment values.
5. Run `uv run --frozen pytest -q tests/test_workspace.py`.

### 3. Parse and validate namespaced upstream inputs

Files:

- `src/irigate/selection.py`
- `src/irigate/app.py` (configured-upstream model callback only)
- `tests/test_selection.py`

Steps:

1. Extend immutable selection objects with validated per-upstream input mappings.
2. Pass configured upstream models, rather than keys alone, into `parse_selection`.
   The HTTP adapter callback must return that mapping; session binding remains Phase 4.
3. Separate selector parameters from `<upstream-key>.<input-name>` parameters.
4. Add RED tests for the accepted filesystem form and rejection of implicit selection, reverse-only selection, excluded inputs, missing required inputs, duplicates, unknown names, relative paths, and disallowed roots.
5. Validate and canonicalize workspace values during selection parsing.
6. Run `uv run --frozen pytest -q tests/test_selection.py`.

### 4. Bind inputs to Streamable HTTP sessions

Files:

- `src/irigate/app.py`
- `tests/test_transport.py`

Steps:

1. Preserve the validated input mapping in the existing request/session selection context.
   The MCP SDK creates the session ID inside its manager, so the HTTP adapter captures the successful response header and records the immutable binding before the client can issue its next request.
2. Add HTTP-level RED tests proving `upstreams=filesystem` exposes filesystem tools only and invalid workspace parameters return JSON HTTP 400 before upstream activation.
3. Add a test proving a later request cannot alter inputs for an established MCP session; fail closed rather than silently rebinding.
4. Keep `agent` validation and Origin enforcement unchanged.
5. Run `uv run --frozen pytest -q tests/test_transport.py`.

### 5. Render per-session arguments and manage isolated workers

Files:

- `src/irigate/broker.py`
- `src/irigate/upstream.py`
- `tests/test_isolation.py`
- `tests/fixtures/` (add a credential-free fixture only if the official filesystem server is too heavy for deterministic tests)

Steps:

1. Add RED broker tests proving two sessions with different workspaces receive distinct processes and arguments.
2. Add tests proving identical inputs in one session reuse a worker, while another session remains isolated.
3. Include a stable input fingerprint in the isolated worker key without placing the raw workspace in metrics/audit output.
4. Render `{workspace}` into worker-local arguments immediately before `StdioServerParameters` construction.
5. Confirm idle expiry removes the full keyed instance and allows clean recreation.
6. Run the focused isolation and lifecycle tests.

### 6. Update the benchmark profile and durable documentation

Files:

- `profiles/benchmark-heavy.yaml`
- `profiles/AGENTS.md`
- `src/irigate/AGENTS.md`
- `tests/AGENTS.md`
- `README.md`
- `IMPLEMENTATION.md`

Steps:

1. Replace the benchmark filesystem server's fixed repository argument with `{workspace}`.
2. Declare `filesystem.inputs.workspace` and an approved `allowed_roots` pattern. Use the narrowest pattern that covers intended projects; do not default to `/**`.
3. Document query syntax, explicit-selection requirement, glob semantics, canonicalization, non-shareability, session binding, and examples with URL encoding.
4. Update the applicable DOX contracts and ownership descriptions; remove any stale claim that arguments are always fully static.
5. Do not modify the source `settings.json` or swap file.

### 7. Verification and closeout

Run:

1. `uv run --frozen pytest -q tests/test_config.py tests/test_workspace.py tests/test_selection.py tests/test_transport.py tests/test_isolation.py`
2. `GITHUB_PERSONAL_ACCESS_TOKEN=validation-only uv run --frozen python -m irigate --config profiles/benchmark-heavy.yaml --check`
3. `uv run --frozen pytest -q`
4. A real local smoke test with two temporary workspace directories and two downstream sessions, verifying each filesystem tool view is confined to its own root and both processes expire after idle timeout.
5. `git diff --check`
6. Re-run the code-review graph incrementally and inspect affected flows.
7. Perform the mandatory DOX pass across every changed path.

Expected gates:

- Existing 129 tests remain green and new tests pass.
- Invalid workspace requests return HTTP 400 without spawning an upstream.
- No workspace value appears in audit/runtime-report output.
- A filesystem input never broadens selected upstreams.
- Symlinked or glob-mismatched workspaces cannot escape configured allowed roots.
- Traversal such as `/srv/my/project/../../../what-ever` is authorized only against its canonical destination, never against its original prefix.

## Files likely to change

- `src/irigate/models.py`
- `src/irigate/workspace.py` (new)
- `src/irigate/selection.py`
- `src/irigate/app.py`
- `src/irigate/broker.py`
- `src/irigate/upstream.py`
- `tests/test_config.py`
- `tests/test_workspace.py` (new)
- `tests/test_selection.py`
- `tests/test_transport.py`
- `tests/test_isolation.py`
- `profiles/benchmark-heavy.yaml`
- `README.md`
- `IMPLEMENTATION.md`
- Applicable `AGENTS.md` files

## Risks and tradeoffs

- `**` matching can be implemented incorrectly with catastrophic backtracking. Use segment-based dynamic programming or memoized recursion, not user-derived regular expressions.
- Symlink handling is security-sensitive. Canonicalize the candidate before matching and test both final-component and intermediate-directory symlinks.
- MCP Streamable HTTP query parameters appear on every request. Session input immutability must be explicit to prevent mid-session worker changes.
- Tool schema discovery currently activates an upstream before the first call. Required input validation must happen before that activation.
- A broad pattern such as `/**` intentionally grants the entire filesystem and defeats the jail. Support it syntactically but never use it in the shipped benchmark profile.
- Profile-side environment and tilde expansion can make effective access depend on the broker account. Validation output may show resolved non-secret paths for operability, while missing-variable errors expose names only. Query-side expansion remains prohibited.
- Adding inputs to selection objects affects routing, reload, transport, direct CLI calls, and tests; the graph reports a high blast radius, so focused tests are insufficient without the full suite.

## Resolved decisions

1. The shipped benchmark allowlist uses the narrower `/home/raphael/src` root.
2. Exact `tools=filesystem__...` selectors may carry `filesystem.workspace` when they positively require the filesystem upstream.
3. `/**` is supported as a pattern feature only; no shipped profile grants the global root.

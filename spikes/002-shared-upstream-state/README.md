# Shared upstream state

Verdict: `VALIDATED`

## Candidate runtime

- Python: 3.14.4
- Official MCP Python SDK: 1.28.1
- `code-review-graph`: installed package 2.3.6; MCP `serverInfo.version` reports 3.4.4
- `@upstash/context7-mcp`: 3.2.3

The `code-review-graph` package/server version mismatch is recorded rather than normalized; qualification must fingerprint both package and MCP-reported versions.

## Run

```bash
uv lock
uv run --frozen python verify.py
```

## Candidate rules

- `context7` is tested only for its two read-only, non-destructive tools under one fixed broker-to-upstream identity and environment. Downstream client metadata is not forwarded after the broker initializes the stdio process.
- `code-review-graph` is not admitted to general shared mode. Its process owns a default-repository global, a model cache, and mutating graph/refactor tools. The read-only probe supplies `repo_root` explicitly, but the current profile exposes the whole tool surface.
- The stateful fixture is a positive control: a shared process intentionally leaks client A's state to client B, while two isolated processes do not.

## Source qualification

- Context7 3.2.3 `packages/mcp/src/index.ts` sets `stdioApiKey` and `stdioSessionId` once before connecting and sets `stdioClientInfo` from the broker's single initialization. Its `resolve-library-id` and `query-docs` registrations are annotated `readOnlyHint: true`, `destructiveHint: false`, and `idempotentHint: true`; neither handler changes those globals.
- code-review-graph 2.3.6 `code_review_graph/main.py` declares `_default_repo_root` process-wide and explicitly warns that it is safe only for single-threaded stdio. The same MCP surface exposes `build_or_update_graph_tool`, `run_postprocess_tool`, `apply_refactor_tool`, and `generate_wiki_tool`, all of which write graph data or files. `code_review_graph/embeddings.py` also owns the process-wide `_MODEL_CACHE`.

This admits Context7 only for the fixed-identity, fixed-environment, read-only tool surface tested here. It does not admit arbitrary future Context7 versions or configurations. code-review-graph remains isolated until a profile can restrict and qualify a safe tool subset.

## Expected

```text
VALIDATED: context7 fixed-identity read-only sharing; code-review-graph remains isolated; upstream crash contained
```

## Evidence

| Check | Result |
|---|---|
| Real upstream initialization | code-review-graph and Context7 passed |
| Namespaced `tools/list` | `crg__list_graph_stats` and `context7__resolve_library_id` were present |
| Real upstream calls | Both returned valid results concurrently through persistent stdio sessions |
| Stateful positive control | Shared process exposed client A's state; a fresh isolated process returned `None` |
| Crash isolation | The crash fixture exited with code 23; its worker failed without stopping code-review-graph |
| Process cleanup | No new tracked upstream process remained after broker shutdown |

Observed verifier output:

```text
VALIDATED: context7 fixed-identity read-only sharing; code-review-graph remains isolated; upstream crash contained
```

# spikes

## Purpose

Disposable Phase 0 experiments that validate transport, client compatibility, and upstream-sharing assumptions before production packaging begins.

## Ownership

- `001-streamable-http-roundtrip/` — official `mcp==1.28.1` Streamable HTTP transport, concurrent correlation, Origin policy, and shutdown.
- `002-shared-upstream-state/` — qualification of `code-review-graph` and `context7` as shared upstreams, plus upstream-crash isolation.
- `003-multi-client-compatibility/` — direct Streamable HTTP calls from local CLI clients (Hermes, Kilo/OpenCode, Claude Code, Codex).

## Local Contracts

- Each spike is self-contained: own `pyproject.toml`, own `uv.lock`, own `.venv`. Spikes do not import each other.
- Each spike is disposable: nothing in `src/`, `profiles/`, or production packaging depends on a spike.
- Each spike README records the candidate runtime, expected output, observed verifier output, and a `VALIDATED` / `PARTIAL` / `INVALIDATED` verdict. A spike is only `VALIDATED` once its `verify.py` exits 0 and the recorded evidence matches the observed output.

## Work Guidance

- Run a spike with `uv lock && uv run --frozen python verify.py` from the spike directory.
- Reset a spike with `rm -rf .venv uv.lock` before re-running when the upstream contract under test changes.
- Re-run all three spikes after editing a shared upstream signature or the operator's CLI inventory.
- Do not promote any spike code into production. Spikes that survive become the Phase 1 package skeleton, not the spike files.

## Verification

- `001-streamable-http-roundtrip/verify.py` — initializes the broker, exchanges the full MCP request flow, and asserts shutdown completes.
- `002-shared-upstream-state/verify.py` — proves the qualified shared upstream is read-only, isolates a destructive upstream, and contains an upstream process crash.
- `003-multi-client-compatibility/verify.py` — proves at least two CLI clients can call the broker directly without authentication exposure.
- `python3 ~/.hermes/profiles/hermes-vc/scripts/check-md-links.py --format summary /home/raphael/src/rb/irigate-proxy` — every spike README cross-references its source, plan, and verdict without broken anchors.

## Child DOX Index

None.

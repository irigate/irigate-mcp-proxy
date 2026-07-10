# scripts

## Purpose

Repeatable Phase 6 compatibility and resource-evidence harnesses for the production Irigate broker.

## Ownership

- `compatibility.py` owns real installed-client Streamable HTTP probes and call-count verification.
- `benchmark.py` owns repeated direct-versus-broker measurements for the qualified Context7 upstream.

## Local Contracts

- Harnesses never read or copy authentication file contents; temporary client homes may symlink existing authentication files.
- A client is validated only when its marker is present and the runtime report records exactly one additional broker call.
- Benchmark process counts use baseline-differenced `/proc` command signatures and reconcile logical instance roots with the runtime report.
- Harness failures, orphan processes, and report discrepancies are hard failures; call errors remain measured evidence for the phase gate.
- Context7 measurements cover identical credential-free, workspace-free contexts only and must not be extrapolated to isolated upstreams.
- Generated JSON evidence stays under `.irigate/` and is not committed.

## Work Guidance

- Keep probes non-destructive and use reviewed qualified tool surfaces.
- Report unavailable clients explicitly; never convert missing authentication into a passing result.

## Verification

- `uv run --frozen python scripts/compatibility.py --config profiles/mvp.yaml`
- `uv run --frozen python scripts/benchmark.py --config profiles/benchmark-heavy.yaml --clients 1,5,20 --repetitions 3`

## Child DOX Index

None.

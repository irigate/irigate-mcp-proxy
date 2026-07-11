# tests

## Purpose

Executable contracts for Irigate configuration, background reload, transport, routing, isolation, shutdown, qualification, reporting, and client compatibility.

## Ownership

- `test_*.py` files own the behavioral contracts documented in `IMPLEMENTATION.md`, including CLI tool discovery, agent selector parsing, selected-only activation, and independent shared and isolated worker idle expiry.
- `test_reload.py` owns connection-preserving active replacement, dormant reload behavior, and failed-reload fallback.
- `fixtures/` owns credential-free echo, state, and Context7-shaped MCP servers used only by tests.
- `helpers.py` owns loopback test-server startup and typed test-profile construction.

## Local Contracts

- Tests must not read credential values or depend on operator `.env` files.
- Environment-reference tests use `monkeypatch` with synthetic values and assert that errors/output expose names only.
- Process tests must restore the process table to baseline before passing.
- Every regression test must fail against the behavior it was added to protect.

## Work Guidance

- Keep tests deterministic and loopback-only.
- Prefer public package APIs and CLI subprocesses over private implementation details.
- Use explicit test data; never copy values from the operator environment.
- Pass selectors explicitly when a test exercises narrowed exposure, and cover the bare-URL default-all contract separately.

## Verification

- `uv run --frozen pytest -q`

## Child DOX Index

None.

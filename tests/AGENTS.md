# tests

## Purpose

Executable contracts for Irigate configuration, transport, routing, isolation, shutdown, qualification, reporting, and client compatibility.

## Ownership

- Phase-specific `test_*.py` files own behavioral contracts from `IMPLEMENTATION-PLAN.md`.
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

## Verification

- `uv run --frozen pytest -q`

## Child DOX Index

None.

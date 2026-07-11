# tests

## Purpose

Executable contracts for Irigate configuration, background reload, transport, routing, isolation, shutdown, qualification, reporting, and client compatibility.

## Ownership

- `test_*.py` files own the behavioral contracts documented in `IMPLEMENTATION.md`, including configuration-path precedence, workspace-input schema and allowed-root patterns, CLI tool discovery, calls and process reports, agent attribution, busy/idle/stopped transitions, selector parsing, selected-only activation, and independent shared and isolated worker idle expiry.
- `test_reload.py` owns connection-preserving active replacement, dormant reload behavior, and failed-reload fallback.
- `test_workspace.py` owns canonical workspace resolution, path-segment wildcard matching, traversal handling, and symlink-escape rejection.
- `test_migration.py` owns installed-agent discovery, explicit-file scope, JSON/YAML/TOML conversion, environment safety, conflict handling, backups, and migration CLI behavior.
- `fixtures/` owns credential-free echo, state, and Context7-shaped MCP servers used only by tests.
- `helpers.py` owns loopback test-server startup and typed test-profile construction.

## Local Contracts

- Tests must not read credential values or depend on operator `.env` files.
- Environment-reference tests use `monkeypatch` with synthetic values and assert that errors/output expose names only.
- Missing required-field tests exercise both loader errors and the CLI stderr boundary.
- Process tests must restore the process table to baseline before passing.
- Every regression test must fail against the behavior it was added to protect.

## Work Guidance

- Keep tests deterministic and loopback-only.
- Prefer public package APIs and CLI subprocesses over private implementation details.
- Use explicit test data; never copy values from the operator environment.
- Pass selectors explicitly when a test exercises narrowed exposure, and cover the bare-URL default-all contract separately.
- Selection tests cover canonical namespaced workspace inputs for positive upstream and exact-tool selectors plus every implicit, reverse-only, excluded, duplicate, unknown, empty, missing-required, relative, and unauthorized form.

## Verification

- `uv run --frozen pytest -q`

## Child DOX Index

None.

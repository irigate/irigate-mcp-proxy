# tests

## Purpose

Executable contracts for Irigate configuration, background reload, transport, routing, isolation, shutdown, qualification, reporting, payload logging, and client compatibility.

## Ownership

- `test_*.py` files own the behavioral contracts documented in `IMPLEMENTATION.md`, including configuration-path precedence, profile-scoped XDG runtime-report defaults and overrides, ordered reusable workspace sources and allowed-root patterns, CLI tool discovery, calls and process reports, agent attribution, busy/idle/stopped transitions, selector parsing, selected-only activation, per-session workspace argument rendering, input-keyed isolation, and independent shared and isolated worker idle expiry.
- `test_progressive_disclosure.py` owns static upstream metadata, selected brief tool discovery, exact schema output, bundled Agent Skill availability, and preservation of serving runtime evidence by transient CLI brokers.
- `test_reload.py` owns connection-preserving active replacement, dormant reload behavior, and failed-reload fallback.
- `test_workspace.py` owns canonical workspace resolution, allowed-root matching, descendant authorization, traversal handling, and symlink-escape rejection.
- `test_migration.py` owns installed-agent discovery, explicit-file scope, JSON/YAML/TOML conversion, environment safety, conflict handling, backups, and migration CLI behavior.
- `test_restart.py` owns process-control validation and compatibility, process identity, effective server status, immediate reload signaling, graceful stop signaling and cleanup, command visibility, version help, and CLI behavior.
- `test_logs.py` owns default and configured runtime log paths, start-scoped MCP payload records, private path permissions, file-count rotation, latest-log CLI output, and live follow behavior.
- `test_upstream.py` owns WSL-to-Windows interop endpoint selection, explicit `wsl_path_arguments` and workspace path conversion, payload immutability, and safe conversion or missing-endpoint failures.
- `test_doctor.py` owns schema inference, conservative field selection, merge behavior, backups, comment preservation, and atomic profile repair.
- `test_doctor_cli.py` owns read-only findings, `--apply`, rerun health, JSON output, no-applicable-upstream behavior, and preservation of the serving runtime report.
- `fixtures/` owns credential-free echo, state, workspace-argument, doctor-schema, and Context7-shaped MCP servers used only by tests.
- `helpers.py` owns loopback test-server startup and typed test-profile construction.

## Local Contracts

- Tests must not read credential values or depend on operator `.env` files.
- Environment tests cover mixed literal and referenced strings; reference tests use `monkeypatch` with synthetic values and assert that errors/output expose names only.
- WSL CLI integration tests run only when `/run/WSL` has a live interop socket; conversion units mock `wslpath` so the Linux CI runner does not need WSL tooling.
- Missing required-field tests exercise both loader errors and the CLI stderr boundary.
- Process tests must restore the process table to baseline before passing.
- Every regression test must fail against the behavior it was added to protect.

## Work Guidance

- Keep tests deterministic and loopback-only.
- Prefer public package APIs and CLI subprocesses over private implementation details.
- Use explicit test data; never copy values from the operator environment.
- Pass selectors explicitly when a test exercises narrowed exposure, and cover the bare-URL default-all contract separately.
- Selection tests cover scoped and global workspace sources, ordered fallback and cross-upstream reuse for positive upstream and exact-tool selectors, plus every implicit, reverse-only, excluded, unused, duplicate, unknown, empty, missing-required, relative, and unauthorized form.
- Transport tests prove valid workspace selectors expose only the selected upstream, invalid paths return JSON HTTP 400, and an established MCP session rejects a different canonical input mapping.

## Verification

- `uv run --frozen pytest -q`

## Child DOX Index

None.

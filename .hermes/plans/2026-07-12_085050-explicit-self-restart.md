# Explicit Irigate Self-Restart Implementation Plan

## Goal

Add an explicit `irigate restart` command that validates the newly installed Irigate package, asks the currently running broker for a graceful restart, and causes that broker to replace itself with the package from its existing Python environment via `exec`.

Configuration hot reload remains unchanged. Installation remains an external operator action.

## Current context and assumptions

- `src/irigate/__main__.py` owns CLI dispatch and currently starts the listener through `uvicorn.run(...)`.
- `src/irigate/app.py` already provides graceful lifespan shutdown: the Streamable HTTP manager exits, the profile watcher is cancelled, and `Broker.close()` closes upstream workers.
- `runtime_report_path` is optional and currently points only to metadata metrics. The report has no PID or process identity, so it cannot safely target a restart today.
- The restart mechanism is POSIX-only because it depends on signals and `exec`; Linux and WSL are supported. Native Windows must fail with an explicit unsupported-platform error.
- The installed replacement must be in the same Python environment as the running broker. The server will execute `sys.executable -m irigate ...`; switching to a different virtual environment is outside this feature.
- Existing MCP sessions are intentionally disconnected. There is a short listener outage while the process shuts down and binds again.
- No socket inheritance or zero-downtime handoff will be implemented.
- No automatic file/version detection will be implemented.
- No credentials, environment values, MCP arguments, or upstream commands may enter restart state or command output.
- `README.md` mentions ordered workspace-source fallback in its feature overview, but its operational per-session-input section still demonstrates only `{workspace}` on one upstream. The documentation phase must close this pre-existing gap with scoped-to-global fallback and cross-upstream reuse examples.

## Proposed approach

Use a small control document adjacent to the configured runtime report, rather than adding operational identity to the metadata report itself. For a report at `/path/runtime.json`, derive `/path/runtime.json.control`.

The serving process atomically writes a control document after startup containing:

- control schema version;
- profile name;
- canonical configuration path;
- PID;
- random instance ID generated for this invocation;
- Irigate package version.

`irigate restart` loads the profile without resolving its environment references, reads and validates that control document, verifies that the PID still identifies a live Irigate process on Linux, then validates the replacement with `sys.executable -m irigate --config <canonical-path> --check`. Only after validation succeeds does it send `SIGUSR1`.

The serving process owns the `SIGUSR1` handler. The handler requests Uvicorn shutdown; it does not call `exec` from signal context. After Uvicorn has returned and application lifespan cleanup has closed upstream workers, the outer CLI path atomically calls:

```text
os.execv(sys.executable, [sys.executable, "-m", "irigate", ...normalized server options...])
```

The restarted process creates a new instance ID and replaces the control document. The command waits for that instance-ID transition with a short fixed timeout and reports success or failure. PID remains stable across `exec`, so the instance ID—not PID—is the completion signal.

## Behavioral contract

### Invocation

```text
irigate restart [--config PATH]
```

Configuration path precedence remains explicit `--config`, then `IRIGATE_CONFIG`, then the default path.

### Preconditions

- Platform supports `SIGUSR1` and `execv`.
- Profile loads successfully.
- Profile defines `runtime_report_path`; otherwise restart fails with an actionable error.
- A valid control document exists and matches the selected canonical profile path and profile name.
- The recorded PID is live and still identifies an Irigate process.
- The replacement package passes `--check` for the same profile.

### Success

- The command signals the server.
- The server completes normal Uvicorn/application/broker shutdown.
- The server replaces itself with `sys.executable -m irigate` using normalized startup options.
- The replacement writes a new control instance ID.
- `irigate restart` exits `0` only after observing that new ID.

### Failure

- Validation failure: do not signal the server; print the replacement check error and exit nonzero.
- Missing/stale/mismatched control state: do not signal any PID; print an actionable restart error and exit nonzero.
- Signal failure: report it and exit nonzero.
- Graceful shutdown failure before `exec`: the existing process follows normal Uvicorn failure behavior; no forced second process is launched.
- `exec` failure: log the error and exit nonzero after cleanup. Do not attempt a restart loop.
- Restart completion timeout: command exits nonzero and says the request was sent but the replacement was not observed. It must not send another signal automatically.

## Step-by-step implementation plan

### Phase 1: Define restart state and process identity

Status: Done — `12 passed in 0.03s` from `tests/test_restart.py`.

Objective: introduce a minimal, credential-free control-state abstraction with deterministic path derivation and atomic writes.

Files:

- Create `src/irigate/restart.py`.
- Create `tests/test_restart.py`.
- Update `src/irigate/AGENTS.md`.
- Update `tests/AGENTS.md`.

Steps:

1. Add failing unit tests for deriving `<runtime_report_path>.control` and rejecting a profile without `runtime_report_path`.
2. Add a typed restart-control record with strict validation for schema version, profile, canonical config path, positive PID, non-empty instance ID, and version.
3. Add atomic JSON write/read helpers using an adjacent temporary file plus `os.replace`, matching the runtime-report write style.
4. Add tests for malformed JSON, wrong schema, missing fields, profile/config mismatch, and stale control files.
5. Add a Linux process-identity check that verifies the PID exists and `/proc/<pid>/cmdline` represents Python running `irigate` or an `irigate` console entry point. Keep this check narrow; do not scan the process table.
6. Add tests using the current test process for accepted/rejected process identity without exposing its environment.
7. Run `uv run --frozen pytest -q tests/test_restart.py`.

Gate:

- Control documents are atomic, strictly parsed, and contain no executable arguments, environment values, or credentials.
- A mismatched or reused PID is rejected before signaling.

### Phase 2: Refactor serving into a controllable Uvicorn lifecycle

Status: Todo.

Objective: make graceful shutdown observable to the CLI entry point so `exec` happens only after lifespan cleanup.

Files:

- Modify `src/irigate/__main__.py`.
- Modify `src/irigate/restart.py`.
- Extend `tests/test_restart.py`.

Steps:

1. Add a failing test around a restart coordinator showing that `SIGUSR1` sets a restart request and asks the server to exit, but does not call `exec` in the signal handler.
2. Replace `uvicorn.run(...)` with explicit `uvicorn.Config` and `uvicorn.Server` construction while preserving host, port, logging, and lifespan behavior.
3. Integrate restart signal handling with Uvicorn’s supported signal-capture lifecycle. Preserve existing `SIGINT`/`SIGTERM` shutdown behavior; only `SIGUSR1` sets the restart flag.
4. Write the control document only when the serving process is ready to accept restart requests. Remove it during ordinary final shutdown only if it still belongs to the current instance.
5. After `Server.run()` returns, branch on the restart flag. Ordinary shutdown returns normally; restart invokes a small injectable exec helper after application cleanup.
6. Reconstruct normalized server arguments from resolved startup state: canonical `--config` path plus `--require-qualified-sharing` only when active. Do not preserve subcommands, `--check`, ambient shell wrappers, or arbitrary original arguments.
7. Call `os.execv(sys.executable, [sys.executable, "-m", "irigate", ...])` exactly once.
8. Add tests with an injected/fake exec function proving ordering: shutdown completed, owned control state removed or superseded, then exec called with the expected interpreter/module/config/strict-mode arguments.
9. Add tests proving `SIGINT` and normal server return do not exec.
10. Run `uv run --frozen pytest -q tests/test_restart.py tests/test_shutdown.py tests/test_reload.py`.

Gate:

- Broker/upstream cleanup completes before exec.
- Existing normal shutdown and configuration reload tests remain green.
- No listener socket is inherited intentionally.

### Phase 3: Add the `restart` CLI command

Objective: validate and request restart from a separately invoked CLI process.

Files:

- Modify `src/irigate/__main__.py`.
- Modify `src/irigate/restart.py`.
- Extend `tests/test_restart.py`.

Steps:

1. Add parser tests for `irigate restart --config PATH` and the existing global `--config PATH restart` form, matching current subcommand conventions.
2. Implement replacement validation as a subprocess using the current command process’s `sys.executable -m irigate --config <canonical-path> --check`.
3. Ensure the validation subprocess receives the current environment but its output is relayed only through the existing credential-safe configuration error boundary.
4. Read and validate control state after replacement validation, then immediately recheck process identity before signaling to narrow the PID-race window.
5. Send `SIGUSR1` with `os.kill` only after all checks pass.
6. Poll only the single control path for a bounded period, looking for the same profile/config/PID and a different instance ID. Use a small constant interval and timeout; do not scan ports or processes.
7. Return `0` with a concise success message after observing replacement. Return distinct nonzero errors for unsupported platform, invalid replacement, no running server, stale/mismatched state, signal failure, and completion timeout.
8. Add subprocess-level tests for:
   - no `runtime_report_path`;
   - missing control document;
   - malformed or mismatched control document;
   - replacement `--check` failure without signaling;
   - stale/dead PID;
   - successful signal and instance transition using a disposable helper process;
   - signal accepted but no transition before timeout;
   - unsupported platform through an injected capability boundary.
9. Run `uv run --frozen pytest -q tests/test_restart.py tests/test_cli_ps.py tests/test_config.py`.

Gate:

- The command cannot signal before replacement validation.
- The command cannot target a process from another profile.
- Success means a replacement instance was actually observed, not merely that `kill()` returned successfully.

### Phase 4: End-to-end process replacement test

Objective: prove real installation-style code replacement semantics without modifying the developer environment.

Files:

- Extend `tests/test_restart.py` or create `tests/test_restart_integration.py` if separation improves process cleanup.
- Potentially add a credential-free fixture under `tests/fixtures/` only if the package entry point cannot expose enough evidence.

Steps:

1. Start Irigate as a real subprocess with a temporary profile, free loopback port, runtime report path, and one fixture upstream.
2. Wait for the control document and confirm the MCP listener responds.
3. Record PID and instance ID.
4. Run `python -m irigate restart --config <profile>` as a second subprocess.
5. Assert restart exits `0`, the server PID is unchanged, the instance ID changed, and the listener becomes available again.
6. Assert an MCP request works after restart and no upstream fixture process is orphaned.
7. Terminate the restarted broker normally and assert its owned control document is removed.
8. Add a failure-path integration test where replacement validation fails and prove the original broker remains available with the same instance ID.
9. Run the integration test repeatedly enough to expose lifecycle races, but keep the committed test deterministic and single-run.

Gate:

- Real `exec` is exercised, not mocked.
- PID continuity, instance transition, listener recovery, worker cleanup, and failed-validation preservation are proven.

### Phase 5: Documentation and DOX reconciliation

Objective: document the operator workflow, the intentionally narrow restart boundary, and the already-implemented cascading workspace-input contract missing from the operational README guidance.

Files:

- Modify `README.md`.
- Modify `IMPLEMENTATION.md`.
- Modify `src/irigate/AGENTS.md`.
- Modify `tests/AGENTS.md`.
- Review root `AGENTS.md`; update it only if the project-wide architectural contract changes.

Steps:

1. Expand README’s `Per-session input` section with a profile containing at least two isolated upstreams whose placeholders use ordered sources such as `{filesystem.workspace|workspace}` and `{git.workspace|filesystem.workspace|workspace}`.
2. Add request examples proving precedence: a scoped value wins when supplied; otherwise the first available fallback wins; one global `workspace=` value can populate every positively selected upstream that references it.
3. State the fail-closed boundaries next to the examples: inputs never select upstreams, only referenced sources are accepted, duplicate or unused values fail, and every resolved target is independently checked against that upstream’s `allowed_roots`.
4. Keep terminology aligned across README, `IMPLEMENTATION.md`, root `AGENTS.md`, `src/irigate/AGENTS.md`, and selection tests: call this an ordered scoped-to-global source fallback, and describe cross-upstream reuse separately rather than implying recursive configuration inheritance.
5. Document the restart workflow: finish installation, run `irigate restart`, expect active MCP sessions to reconnect.
6. State that restart uses the same Python environment as the running broker and cannot switch virtual environments.
7. State that configuration edits continue to use connection-preserving hot reload; restart is for installed code replacement.
8. Document the control-file location, credential-free schema boundary, POSIX support, validation-before-signal rule, graceful shutdown, short outage, and stable-PID/new-instance semantics.
9. Add `restart.py` ownership and restart contracts to the nearest DOX files.
10. Update test ownership for restart unit, CLI, and integration behavior.
11. Perform the required DOX pass across every changed path. Leave root `AGENTS.md` unchanged if no project-wide rule or child index changed, and record that reason in closeout.

Gate:

- README’s operational section demonstrates scoped precedence, global fallback, and one supplied workspace reused across multiple selected upstreams.
- Runtime behavior, public docs, implementation docs, and nearest AGENTS contracts agree.

### Phase 6: Full verification

Objective: verify the complete feature and repository contract.

Commands:

```text
uv run --frozen pytest -q
uv run --frozen python -m irigate --config profiles/mvp.yaml --check
uv run --frozen python -m irigate restart --help
```

Also inspect:

```text
git diff --check
git status --short --branch
git diff -- src/irigate tests README.md IMPLEMENTATION.md
```

Expected results:

- Full test suite passes.
- Existing profile validation passes.
- Restart help describes explicit validated self-replacement.
- No credential values, transient control files, temporary JSON files, or process artifacts are tracked.
- Existing unrelated changes in `site` and `settings.json` remain untouched.

## Files likely to change

- `src/irigate/restart.py` — new control-state, validation, signal, wait, and exec coordination.
- `src/irigate/__main__.py` — parser command, explicit Uvicorn lifecycle, restart dispatch.
- `tests/test_restart.py` — unit and CLI contracts.
- `tests/test_restart_integration.py` — optional dedicated real-exec test.
- `README.md` — operator workflow and limitations.
- `IMPLEMENTATION.md` — runtime lifecycle and control-state design.
- `src/irigate/AGENTS.md` — module ownership and durable contracts.
- `tests/AGENTS.md` — test ownership and verification scope.

Root `AGENTS.md` should remain unchanged unless implementation reveals a project-wide architectural decision or a new child boundary.

## Risks and tradeoffs

- **Same-environment limitation:** `sys.executable -m irigate` loads the package installed into the running interpreter’s environment. Installing elsewhere will not switch the server. This is explicit scope, not auto-detected behavior.
- **Session interruption:** all Streamable HTTP sessions end during restart. Socket inheritance would complicate Uvicorn ownership and is deliberately excluded.
- **PID reuse:** a bare PID file would risk signaling an unrelated process. Profile/config matching plus Linux process identity narrows this without introducing a daemon or control socket.
- **Signal integration:** Uvicorn owns normal signal handling. Implementation must use its supported server lifecycle rather than installing conflicting handlers around `uvicorn.run`.
- **Control-file staleness:** crashes can leave state behind. Every command must treat the document as a claim requiring live-process verification, never as proof by itself.
- **Validation is not rollback:** `--check` proves importability and profile validity, not every runtime interaction. A replacement may still fail to bind or initialize later. Automatic rollback is outside scope.
- **Command environment:** the separately launched `restart` command must come from the newly installed environment. Operator documentation must not imply that a different global `irigate` binary can update the running environment.

## Explicit non-goals

- Automatic version or filesystem watching.
- Installing or upgrading Irigate from inside the server.
- Switching Python interpreters or virtual environments.
- Zero-downtime listener/socket handoff.
- Preserving downstream MCP sessions or in-memory metrics across restart.
- Automatic rollback or repeated restart attempts.
- Remote restart over MCP/HTTP.
- Native Windows restart support.

## Open questions to resolve before implementation

1. **Completion timeout:** recommended default is 10 seconds, fixed internally for the first version. A public timeout option is unnecessary unless real deployments prove it is needed.
2. **Process identity check:** confirm Linux/WSL-only support is acceptable. If macOS is required immediately, replace `/proc` validation with a portable control channel or platform-specific process inspection.
3. **Runtime report requirement:** recommended behavior is to require `runtime_report_path` for restart and derive the control path from it. Adding a second configurable state path is unnecessary unless operators need restart without reports.
4. **Metrics continuity:** recommended behavior is reset-on-restart because the process image and all in-memory state are replaced.

## Recommended implementation batches

1. `feat(runtime): add restart control state and graceful exec lifecycle`
   - restart module, explicit Uvicorn lifecycle, signal coordination, unit tests, nearest DOX updates.
2. `feat(cli): add validated irigate restart command`
   - CLI command, replacement validation, completion wait, subprocess and real-exec tests.
3. `docs(restart): document explicit self-restart workflow`
   - README, IMPLEMENTATION, final DOX reconciliation.

Do not commit during plan execution unless the user separately requests implementation and approves the batch list under the repository’s commit workflow.

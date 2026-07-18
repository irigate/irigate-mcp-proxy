# Irigate

> Shared local MCP infrastructure for developers running multiple AI coding agents.

<p align="center">
  <img src="assets/logo.svg" alt="Irigate — an Iris flower opening into a gateway" width="760">
</p>

Irigate is a loopback-only MCP broker. It lets local agent sessions share explicitly qualified stdio MCP servers, reducing duplicate processes while providing metadata-only runtime reports, one audit record for every completed or rejected tool call, and local start-scoped MCP request/response logs.

## Feature overview

| | Capability | | Capability |
|---|---|---|---|
| **⌁** | **One local MCP endpoint**<br>Connect Hermes, Claude Code, Codex, and other Streamable HTTP clients to the same loopback broker. | **⟲** | **Connection-preserving reloads**<br>Apply profile changes in the background without disconnecting active AI-agent sessions. |
| **◈** | **Selective process reuse**<br>Share qualified stdio servers across compatible sessions and restart only upstreams whose configuration changed. | **⛨** | **Fail-closed sharing**<br>Keep upstreams isolated by default; sharing requires explicit opt-in and an upstream-specific qualifier. |
| **⎇** | **Exact namespaced routing**<br>Expose deterministic `<upstream>__<tool>` names and reject ambiguous or unknown routes. | **◎** | **Session isolation**<br>Scope non-shareable workers to downstream sessions so context-bound state never leaks across agents. |
| **⚡** | **Explicit concurrency**<br>Choose serial or parallel execution per upstream, with independent queues and bounded call timeouts. | **◷** | **Bounded lifecycle**<br>Shut down each idle upstream on its configured timeout, restart it on demand, and terminate children without leaving orphans. |
| **◇** | **Layered observability**<br>Keep reports and audit output metadata-only; inspect full local tool requests and responses only through protected rotating logs. | **⚖** | **Measured compatibility**<br>Run qualification, multi-client compatibility checks, and repeatable 1/5/20-client resource benchmarks. |
| **⌘** | **Direct CLI tool calls**<br>Invoke one namespaced MCP tool from automation without starting the HTTP listener. | **▦** | **Process and usage inspection**<br>Use `irigate ps` to see live instances, busy/idle state, idle duration and timeout, and per-agent usage. |

An optional bundled Agent Skill provides progressive disclosure for large tool catalogs: inspect configured upstream metadata, list one upstream's brief tool metadata, load one exact schema, then call that tool without registering every schema in the agent context.

## Development highlights

Per-session inputs let a client supply an approved value when starting an isolated upstream. The currently supported input is a required directory named `workspace`:

- Profiles can declare one reserved, required `workspace` input with `type: directory`, a non-empty `allowed_roots` list, and exactly one standalone placeholder. `{workspace}` remains valid; ordered forms such as `{filesystem.workspace|github.workspace|workspace}` choose the first supplied source.
- Each `allowed_roots` entry authorizes that directory and all of its subdirectories. Profile-side leading `~` and `${ENV_NAME}` references are expanded under strict rules; environment-derived roots must be absolute.
- Workspace authorization resolves the requested directory and each literal pattern prefix canonically before matching. Traversal, sibling-prefix confusion, nonexistent paths, files, and symlink escapes fail closed.
- A valid scoped or global input is fixed for the downstream MCP session, rendered into each selected worker's local argument list, and included in each isolated worker's non-raw context fingerprint. One `workspace=` query value can therefore feed multiple upstreams that list it as a fallback.

Input values are accepted only when a positively selected upstream or exact tool references that source in its placeholder. Bare and reverse-only URLs cannot supply dynamic inputs, unused sources fail closed, and workspace values never enter audit records or runtime reports.

## Problem hypothesis

MCP-capable coding agents commonly start stdio MCP servers as child processes. Several concurrent Hermes, Claude Code, Codex, or worker sessions can therefore start duplicate copies of the same expensive server.

A broker may improve this when:

- Several agent sessions run concurrently.
- An upstream has meaningful startup or memory cost.
- The upstream is safe to share between sessions.
- The sessions use compatible state, workspace, and credential contexts.

Sharing is not universally safe. Some MCP servers retain client-specific state, and distinct workspaces or credentials may still require separate instances. Irigate must prove the benefit per upstream rather than assuming every N×M process set can collapse to M.

## Website

The public website and documentation are maintained in the `site/` git submodule, backed by [`irigate/irigate.github.io`](https://github.com/irigate/irigate.github.io). The website repository owns Astro dependencies, content, verification, GitHub Pages deployment, and custom-domain operations. This source repository remains authoritative for broker behavior, architecture, benchmark evidence, and brand source assets.

Initialize the website after cloning this repository:

```bash
git submodule update --init site
```

Website changes require two commits: commit and push inside `site/` first, then commit the updated `site` pointer in this repository.

## Requirements

- Python 3.11 through 3.14.
- [`uv`](https://docs.astral.sh/uv/) for installation and execution.
- Node.js with `npx` for the Context7 upstream in `profiles/mvp.yaml`.
- An installed `code-review-graph` executable for the isolated code-review-graph upstream.

The default profile defines real MCP upstreams. An upstream starts only when an agent selects it; its first selected use may download pinned or current package artifacts and require network access.

## Install

Install Irigate as a standard user application from a repository checkout:

```bash
uv tool install --force --from . irigate
```

`uv` installs the launcher in `~/.local/bin/irigate` and manages its dependencies in an isolated environment. Ensure `~/.local/bin` is on `PATH`, then use `irigate` without activating the project virtual environment:

```bash
irigate --help
irigate --config profiles/mvp.yaml --check
```

Reinstall after updating the checkout, or remove the application:

```bash
uv tool install --force --from . irigate
uv tool uninstall irigate
```

For development, create the project environment from the locked dependencies instead:

```bash
cd irigate-proxy
uv sync --frozen
```

Run the development checkout and confirm that the default profile loads without starting upstream processes:

```bash
uv run --frozen irigate --help
uv run --frozen irigate --config profiles/mvp.yaml --check
```

## Configuration

Irigate reads `~/.config/irigate/config.yaml` by default. Set `IRIGATE_CONFIG` to use another file, or pass `--config`; the command-line argument takes precedence over the environment variable. Profiles are validated before any upstream process starts: unknown fields, duplicate YAML keys, unsupported transports, invalid routing keys, non-loopback listeners, and missing environment references are rejected.

```yaml
name: local
host: 127.0.0.1
port: 8765
runtime_report_path: .irigate/runtime-report.json

upstreams:
  context7:
    description: Resolve library identifiers and query current library documentation.
    transport: stdio
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
    env:
      CONTEXT7_API_KEY: ${CONTEXT7_API_KEY}
      LOG_LEVEL: info
    shareable: true
    qualifier: context7-readonly-v3
    concurrency: serial
    call_timeout_seconds: 30
    idle_timeout_seconds: 300
    failure_threshold: 5
    crash_threshold: 2
```

### Broker fields

| Field | Required | Default | Contract |
| --- | --- | --- | --- |
| `name` | Yes | — | Profile identifier using lowercase letters, digits, and hyphens. It labels `--check` output and runtime reports so operators can distinguish configurations; it does not affect routing. |
| `host` | No | `127.0.0.1` | Listener address. Only `localhost` or an IP loopback address is accepted. |
| `port` | No | `8765` | Streamable HTTP listener port, from 1 through 65535. |
| `runtime_report_path` | No | Disabled | JSON report destination. The file is refreshed atomically and contains process statistics plus validated agent labels, never payloads or credentials. |
| `runtime_log_path` | No | `~/.local/log/irigate/<name>/` | Exact directory for protected start-scoped MCP payload logs. Relative paths are anchored to the profile directory. Changing it requires a broker restart. |
| `upstreams` | Yes | — | Non-empty mapping of routing keys to stdio upstream definitions. |

### Required broker-field example

`name` and `upstreams` belong in the selected broker profile. They are not HTTP query parameters, and Irigate does not accept `--name` or `--upstreams` CLI flags. The smallest useful profile includes both required broker fields and the two required fields for each upstream:

```yaml
name: local-development
upstreams:
  context7:
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
    idle_timeout_seconds: 300
```

Choose `name` as a stable identifier for where or why the profile runs, such as `local-development`, `project-docs`, or `benchmark`. It appears in validation output and runtime reports but does not change routing. Choose each upstream key, such as `context7`, as the stable tool namespace: the key becomes the prefix in `<upstream-key>__<tool-name>`. Add every MCP server Irigate should be able to expose under `upstreams`; at least one entry is required.

Save that profile as `~/.config/irigate/config.yaml` to use it by default:

```bash
mkdir -p ~/.config/irigate
cp profiles/local.yaml ~/.config/irigate/config.yaml
uv run --frozen irigate --check
uv run --frozen irigate
```

The first command validates the required fields without starting upstreams. The second starts the broker with profile name `local-development` and the configured `context7` upstream.

For a different profile, set its full path in the environment or override it for one invocation:

```bash
export IRIGATE_CONFIG="$HOME/.config/irigate/work.yaml"
uv run --frozen irigate --check
uv run --frozen irigate --config profiles/benchmark-heavy.yaml --check
```

If either broker field is absent, Irigate exits before starting the HTTP listener and writes an actionable configuration error to stderr with a minimal example.

An upstream key becomes the prefix in every exposed `<upstream-key>__<tool-name>` route. Keys must start with a lowercase letter and may contain lowercase letters, digits, and hyphens.

### Upstream fields

| Field | Required | Default | Contract |
| --- | --- | --- | --- |
| `description` | No | — | Short operator-authored purpose used by the optional progressive-disclosure catalog. It never starts the upstream. |
| `transport` | No | `stdio` | Only `stdio` is supported. |
| `command` | Yes | — | One executable token. Put command arguments in `args`. |
| `args` | No | `[]` | Argument list. Environment references and credentials are not accepted. An upstream with `inputs.workspace` must contain exactly one standalone workspace placeholder. Pipe-separated sources are checked left to right and rendered from the canonical session input before process startup. |
| `cwd` | No | Inherit broker directory | Working directory for the stdio process. Migration resolves relative agent paths against the owning user or project directory. |
| `env` | No | `{}` | Child environment mapping. Values may be literal strings or explicit `${BROKER_ENV_NAME}` references. Use references for credentials so secret values stay out of the profile. |
| `inputs` | No | `{}` | Per-session input declaration. Only a required `workspace` directory is supported. It needs non-empty `allowed_roots`, requires `shareable: false`, and is immutable after the MCP session is established. |
| `shareable` | No | `false` | Requests one process shared across downstream sessions. Sharing is admitted only by a registered qualifier. |
| `qualifier` | Conditional | — | Required when `shareable: true`; rejected otherwise. Currently registered: `context7-readonly-v3` for the `context7` key. |
| `concurrency` | No | `serial` | `serial` executes one call at a time; `parallel` permits concurrent calls within the worker. |
| `call_timeout_seconds` | No | `30` | Per-call timeout greater than 0 and no more than 3600 seconds. It does not control process idleness. |
| `idle_timeout_seconds` | Yes | — | Per-process inactivity TTL greater than 0 and no more than 86400 seconds. |
| `failure_threshold` | No | `5` | Error count from 1 through 100 that degrades a shared upstream. |
| `crash_threshold` | No | `2` | Crash count from 1 through 100 that degrades a shared upstream. |

Each spawned worker tracks its own idle timeout. A worker shuts down only when its TTL expires with no queued or active calls. Shared and session-isolated workers expire independently, and the next routed call starts a fresh process in the same effective sharing mode. A long-running call remains governed by `call_timeout_seconds`, not by the idle timeout.

Literal strings are passed directly to the child process. `${ENV_NAME}` values are resolved from the broker process without being written into the profile, audit log, runtime report, or validation output:

```bash
export CONTEXT7_API_KEY='...'
uv run --frozen irigate --config profiles/local.yaml --check
```

### Migrate installed agent configurations

`irigate migrate` discovers user and current-project MCP configurations for Claude Code, Codex CLI, Cursor, Gemini CLI, and Hermes. It presents an interactive numbered selection, moves each selected stdio server into the Irigate profile, and replaces those direct server entries with one agent-specific Streamable HTTP connection to Irigate. Existing remote MCP entries and unrelated agent settings remain in place.

```bash
uv run --frozen irigate migrate --config ~/.config/irigate/config.yaml
uv run --frozen irigate migrate --all --config ~/.config/irigate/config.yaml
uv run --frozen irigate migrate ~/.cursor/mcp.json --config ~/.config/irigate/config.yaml
```

Providing a file bypasses discovery and migrates only that file. Non-interactive use requires either a file or `--all`. Existing files receive adjacent `.irigate.bak` backups before replacement; a pre-existing backup stops the migration rather than overwriting evidence. New upstreams default to isolated, serial execution with a 30-second call timeout and 300-second idle timeout. Existing remote MCP servers are not moved.

Agent-local environment values are never copied into the Irigate profile. Every migrated child environment variable becomes an explicit `${ENV_NAME}` broker reference, and that variable must already be exported in the environment running the migration. The same environment must be available when Irigate runs. Conflicting normalized upstream names or unsupported configuration shapes fail before any file changes.

While serving, Irigate watches the selected profile. Changed active upstreams must initialize successfully before routing switches. Added and changed dormant upstreams remain stopped until selected. Invalid updates leave the last valid active configuration available. Changes to `name`, `host`, `port`, `runtime_report_path`, or `runtime_log_path` require restarting the broker.

## Run

Start the broker in the foreground with strict sharing admission:

```bash
uv run --frozen irigate \
  --config profiles/mvp.yaml \
  --require-qualified-sharing
```

Inspect the installed version and all available commands:

```bash
uv run --frozen irigate --version
uv run --frozen irigate --help
```

The root help lists `reload` and `stop`; each command's `--help` output also identifies the running Irigate version so a stale installed executable is visible immediately.

The broker listens at `http://127.0.0.1:8765/mcp` without starting upstreams. A client may use the bare URL to expose all configured upstreams, or add a selector to narrow the set. Qualification, schema discovery, and process startup happen on first use. Each upstream's `idle_timeout_seconds` shuts down that process independently after inactivity; the next routed call starts a fresh process without changing the downstream session.

### Agent-side selection

The agent URL does not repeat the broker profile's required `name` and `upstreams` fields. It connects to an already-running profile. The examples below assume Irigate was started with `--config profiles/mvp.yaml`; that profile contains `name: mvp` and defines the `context7` and `code-review-graph` upstream keys. Use exact tools for the narrowest and recommended agent configuration:

```text
http://127.0.0.1:8765/mcp?tools=context7__resolve-library-id,context7__query-docs
```

Select complete upstreams by their keys from the active broker profile when the agent needs their full tool surfaces:

```text
http://127.0.0.1:8765/mcp?upstreams=context7,code-review-graph
```

Prefix an upstream with `!` when the agent starts that MCP server directly and wants every other configured Irigate upstream:

```text
http://127.0.0.1:8765/mcp?upstreams=!code-review-graph
```

Positive and reverse selectors may be mixed. Positive names form the base set and exclusions are subtracted regardless of order:

```text
http://127.0.0.1:8765/mcp?upstreams=context7,code-review-graph,!code-review-graph
```

This selects only `context7`. Omitting both selector parameters exposes all configured upstreams unchanged. Reverse-only selection also starts from all currently configured upstreams, so profile reloads can broaden it when a new upstream is added. Prefer `tools=` for least privilege. When selection is used, provide only one `tools` or `upstreams` parameter; repeated parameters, unknown names, malformed tokens, unrelated query parameters, and an empty result are rejected. Exact tool selection never supports `!` because excluding one tool cannot avoid starting its upstream.

### Per-session input

An upstream may declare one required directory input named `workspace`. This filesystem server is one example; the input contract is not specific to that server. The following profile permits the home directory and all of its subdirectories:

```yaml
filesystem:
  command: npx
  args: ["-y", "@modelcontextprotocol/server-filesystem", "{workspace}"]
  inputs:
    workspace:
      type: directory
      required: true
      allowed_roots: ["${HOME}"]
  shareable: false
  idle_timeout_seconds: 300
```

Select the upstream positively and URL-encode the absolute workspace value:

```text
http://127.0.0.1:8766/mcp?upstreams=filesystem&filesystem.workspace=${HOME}
```

Here `${HOME}` denotes the absolute value supplied by the client; Irigate does not expand shell syntax in query values.

An exact tool selector for the configured upstream may carry the same input. Inputs do not select upstreams by themselves: bare URLs, reverse-only selectors, excluded upstreams, missing or duplicate values, relative paths, and unknown input names are rejected before activation. The canonical mapping is bound to the first successful MCP session response; later requests for that session must present the identical mapping.

Each configured `allowed_roots` entry permits its canonical directory and all descendants. Profile-side leading `~` and braced `${ENV_NAME}` references expand at load time under strict validation, but query values never expand shell syntax. Irigate strictly resolves the requested directory before authorization, so traversal and symlink paths are judged by their canonical destination.

Add an explicit `agent=` label to attribute calls in the runtime report:

```text
http://127.0.0.1:8765/mcp?upstreams=code-review-graph&agent=codex
```

Agent labels are metadata, not authentication. They must be 1–64 letters, digits, dots, underscores, or hyphens and are recorded only after a valid tool call. Omitted labels are grouped as `anonymous`; Irigate does not guess identity from client headers.

### CLI operations

#### Optional progressive-disclosure Agent Skill

Irigate bundles an AgentSkills-compatible integration for agents that have shell access and need only a few tools from a large catalog. Locate the installed skill and copy that directory into the explicit skill directory used by the agent:

```bash
irigate skill-path
cp -R "$(irigate skill-path)" <agent-skill-directory>/irigate-progressive
```

The skill uses four explicit layers:

```bash
# Layer 1: static profile metadata; no upstream startup or environment resolution
irigate upstreams --config profiles/mvp.yaml --json

# Layer 2: names and descriptions from one upstream; schemas are omitted
irigate tools --config profiles/mvp.yaml --upstream code-review-graph --json

# Layer 3: one exact namespaced schema
irigate schema --config profiles/mvp.yaml code-review-graph__get_minimal_context_tool

# Layer 4: one exact call
irigate call --config profiles/mvp.yaml \
  code-review-graph__get_minimal_context_tool \
  --arguments '{"repo_root":"/path/to/project","task":"review changes"}'
```

`upstreams` reads only validated metadata and does not require referenced environment values. `tools`, `schema`, and `call` initialize only the selected upstream and close it before returning. Separate commands therefore do not preserve an isolated upstream session; use the standard Streamable HTTP endpoint for stateful or multi-call workflows. The progressive integration deliberately keeps exact tool names visible instead of adding a generic dispatcher that would hide them from approval and audit surfaces.

#### Tool discovery and calls

List the exact namespaced tools available from a profile before configuring an agent:

```bash
uv run --frozen irigate tools --config profiles/mvp.yaml
```

The command prints one `<upstream>__<tool>` name per line so its output can be copied into `tools=`. Tool schemas are runtime metadata rather than static profile fields, so discovery temporarily starts and initializes every configured upstream, then closes all spawned processes. It may therefore download upstream packages, use the network, and require the profile's referenced environment variables. Use `--check` instead when only configuration validation without startup is needed.

Call a namespaced tool directly from a shell without starting the HTTP listener:

```bash
uv run --frozen irigate call --config profiles/mvp.yaml \
  code-review-graph__build_or_update_graph_tool \
  --arguments '{"repo_root":"/path/to/project","full_rebuild":false}'
```

`--arguments` accepts one JSON object and defaults to `{}`. The command prints the complete MCP `CallToolResult` as JSON, exits `0` for a successful tool result, `1` for an MCP or upstream error, and `2` for invalid configuration or arguments. The upstream starts only for this call and is closed before the command exits. A valid direct call creates its own MCP log file. Pass credentials through the profile's environment references, never through tool arguments.

Inspect the latest runtime snapshot in a `ps`/`netstat`-style table:

```bash
uv run --frozen irigate ps --config profiles/mvp.yaml
uv run --frozen irigate ps --config profiles/mvp.yaml --json
```

Each table row identifies an upstream/agent pair and shows effective mode, live process count, activity state (`busy`, `idle`, or `stopped`), elapsed idle time, configured idle timeout, calls, and failures. `IDLE_FOR` is `-` while busy or stopped; while idle it is calculated from the report's UTC `idle_since` timestamp, so it continues advancing between report writes. `--json` returns the complete schema-version-3 report, including `activity_state`, `active_calls`, `idle_since`, and `idle_timeout_seconds`, for automation. This command reads `runtime_report_path` without starting upstreams or resolving their environment references; a report left by a stopped broker retains cumulative usage from that run.

Print the newest MCP call log for the selected profile, or follow appended JSON-line records live on stdout:

```bash
uv run --frozen irigate logs --config profiles/mvp.yaml
uv run --frozen irigate logs -f --config profiles/mvp.yaml
```

Every server start and valid direct `call` starts a new file under `~/.local/log/irigate/<profile>/` by default. Set the optional profile field `runtime_log_path` to use another exact directory; relative values are anchored to the profile directory. Irigate retains the newest 10 files per profile. The directory is mode `0700` and files are mode `0600`. Each record contains the agent label, complete `tools/call` arguments, complete MCP result or raised error, and duration. These payload logs can contain sensitive tool input or output; unlike audit records and runtime reports, they are not metadata-only. `logs` reads no upstream environment references and starts no processes. `-f` follows the selected file; run it again after a new broker start to follow the new file.

Gracefully stop the server selected by the same profile:

```bash
uv run --frozen irigate stop --config profiles/mvp.yaml
```

Request an immediate connection-preserving profile reload:

```bash
uv run --frozen irigate reload --config profiles/mvp.yaml
```

Serving writes a credential-free `<runtime_report_path>.control` document containing the profile, canonical configuration path, PID, instance ID, and package version. Both commands treat that document as an untrusted claim: they check the selected profile and configuration path and verify that the PID is a live Irigate process. `reload` sends `SIGHUP` to wake the same atomic reload path used by profile watching; exit `0` confirms delivery, while validation or activation failures remain in the server log and leave the last valid configuration active. `stop` sends `SIGTERM` and waits for normal application and child-process cleanup. Neither command resolves upstream environment references. A missing `runtime_report_path`, stale or mismatched control document, non-Irigate PID, or signal failure fails without signaling another process; `stop` also fails when cleanup is not observed.

An agent can combine Irigate with a directly managed MCP server:

```yaml
mcp_servers:
  irigate:
    url: "http://127.0.0.1:8765/mcp?upstreams=!code-review-graph"
  code-review-graph:
    command: code-review-graph
    args: [serve]
```

For a foreground broker, `Ctrl+C` remains equivalent operationally: shutdown drains active calls and closes child processes.

Strict mode rejects the first selected use of Context7 if it cannot be qualified. Omit `--require-qualified-sharing` to downgrade failed selected shared upstreams to isolated mode.

Run qualification without opening the client endpoint when diagnosing startup:

```bash
uv run --frozen irigate qualify --config profiles/mvp.yaml
```

Audit records are written as metadata-only JSON lines to stderr. The default profile atomically refreshes `.irigate/runtime-report.json` with metadata-only process, reuse, timing, failure, and per-agent usage counters. Tool arguments and results remain excluded from both surfaces and are retained only in the protected rotating MCP call logs.

## Not part of the MVP

- Enterprise governance or compliance claims
- User identity, tenant isolation, RBAC, OAuth, or remote access
- Credentials in URLs or dynamic HTTP environment overrides
- Generic secret scanning or response rewriting
- A custom filesystem MCP server or path-guessing middleware
- SSE as the primary client transport
- OpenAI or Anthropic API proxying
- Kubernetes, a web portal, daemon management, or dynamic configuration APIs

## Architecture direction

```text
Hermes / Claude Code / Codex / test clients
                    │
                    │ MCP over Streamable HTTP on loopback
                    ▼
             ┌──────────────┐
             │   Irigate    │
             │              │
             │watched config│
             │ exact routing│
             │ process reuse│
             │ metadata log │
             └──────┬───────┘
                    │ stdio MCP
          ┌─────────┼─────────┐
          ▼         ▼         ▼
      upstream A upstream B upstream C
      isolated   shareable  shareable
      by default only after only after
                 testing    testing
```

Different upstreams must progress independently. Shared instances are permitted only after transport, concurrency, and state-isolation tests pass.

## Implementation

[`IMPLEMENTATION.md`](IMPLEMENTATION.md) documents runtime architecture, module ownership, safety contracts, extension workflows, and verification commands.

## Positioning

The current market hypothesis is documented in [`MARKET-RESEARCH.md`](MARKET-RESEARCH.md).

Irigate is positioned as local AI developer infrastructure, not as a competitor to enterprise control planes such as Microsoft MCP Gateway. Microsoft focuses on Kubernetes deployment, management APIs, Entra authorization, session-aware routing, and a portal. Irigate's narrower hypothesis is workstation-local stdio process consolidation across several coding-agent products.

## Repository contents

- `IMPLEMENTATION.md` — Current architecture, contracts, extension workflows, and verification.
- `MARKET-RESEARCH.md` — Market hypothesis, measured evidence, positioning, and go/no-go criteria.
- `assets/` — Reproducible Iris-gate project mark, lockup, and raster exports.
- `profiles/` — Validated loopback-only runtime and benchmark profiles.
- `src/irigate/` — Installable package, configuration models, loader, and CLI.
- `tests/` — Executable package and runtime contracts.

## Status

- Product scope: loopback-only local MCP broker.
- Validation: Context7 is qualified for shared mode; code-review-graph remains isolated.
- Evidence: process and resident-memory consolidation is established for identical Context7 contexts. Call-latency evidence remains invalid because Context7 throttled the benchmark.
- Market evidence: hypothesis only.
- Next action: rerun the latency benchmark with adequate Context7 quota and observe normal development sessions before making a release decision.

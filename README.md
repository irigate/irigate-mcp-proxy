# Irigate

> Shared local MCP infrastructure for developers running multiple AI coding agents.

<p align="center">
  <img src="assets/logo.svg" alt="Irigate — an Iris flower opening into a gateway" width="760">
</p>

Irigate is a loopback-only MCP broker. It lets local agent sessions share explicitly qualified stdio MCP servers, reducing duplicate processes while providing metadata-only runtime reports and one audit record for every completed or rejected tool call.

## Feature overview

| | Capability | | Capability |
|---|---|---|---|
| **⌁** | **One local MCP endpoint**<br>Connect Hermes, Claude Code, Codex, and other Streamable HTTP clients to the same loopback broker. | **⟲** | **Connection-preserving reloads**<br>Apply profile changes in the background without disconnecting active AI-agent sessions. |
| **◈** | **Selective process reuse**<br>Share qualified stdio servers across compatible sessions and restart only upstreams whose configuration changed. | **⛨** | **Fail-closed sharing**<br>Keep upstreams isolated by default; sharing requires explicit opt-in and an upstream-specific qualifier. |
| **⎇** | **Exact namespaced routing**<br>Expose deterministic `<upstream>__<tool>` names and reject ambiguous or unknown routes. | **◎** | **Session isolation**<br>Scope non-shareable workers to downstream sessions so context-bound state never leaks across agents. |
| **⚡** | **Explicit concurrency**<br>Choose serial or parallel execution per upstream, with independent queues and bounded call timeouts. | **◷** | **Bounded lifecycle**<br>Shut down each idle upstream on its configured timeout, restart it on demand, and terminate children without leaving orphans. |
| **◇** | **Metadata-only observability**<br>Record outcomes, durations, reuse, failures, and process counts without payloads, commands, or credentials. | **⚖** | **Measured compatibility**<br>Run qualification, multi-client compatibility checks, and repeatable 1/5/20-client resource benchmarks. |

## Problem hypothesis

MCP-capable coding agents commonly start stdio MCP servers as child processes. Several concurrent Hermes, Claude Code, Codex, or worker sessions can therefore start duplicate copies of the same expensive server.

A broker may improve this when:

- Several agent sessions run concurrently.
- An upstream has meaningful startup or memory cost.
- The upstream is safe to share between sessions.
- The sessions use compatible state, workspace, and credential contexts.

Sharing is not universally safe. Some MCP servers retain client-specific state, and distinct workspaces or credentials may still require separate instances. Irigate must prove the benefit per upstream rather than assuming every N×M process set can collapse to M.

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

Irigate reads one YAML profile selected with `--config`. Profiles are validated before any upstream process starts: unknown fields, duplicate YAML keys, unsupported transports, invalid routing keys, non-loopback listeners, and missing environment references are rejected.

```yaml
name: local
host: 127.0.0.1
port: 8765
runtime_report_path: .irigate/runtime-report.json

upstreams:
  context7:
    transport: stdio
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
    env:
      CONTEXT7_API_KEY: ${CONTEXT7_API_KEY}
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
| `name` | Yes | — | Profile identifier using lowercase letters, digits, and hyphens. |
| `host` | No | `127.0.0.1` | Listener address. Only `localhost` or an IP loopback address is accepted. |
| `port` | No | `8765` | Streamable HTTP listener port, from 1 through 65535. |
| `runtime_report_path` | No | Disabled | JSON report destination. The file is refreshed atomically and contains metadata only. |
| `upstreams` | Yes | — | Non-empty mapping of routing keys to stdio upstream definitions. |

An upstream key becomes the prefix in every exposed `<upstream-key>__<tool-name>` route. Keys must start with a lowercase letter and may contain lowercase letters, digits, and hyphens.

### Upstream fields

| Field | Required | Default | Contract |
| --- | --- | --- | --- |
| `transport` | No | `stdio` | Only `stdio` is supported. |
| `command` | Yes | — | One executable token. Put command arguments in `args`. |
| `args` | No | `[]` | Static argument list. Environment references and credentials are not accepted here. |
| `env` | No | `{}` | Child environment mapping. Every value must be an explicit `${BROKER_ENV_NAME}` reference. |
| `shareable` | No | `false` | Requests one process shared across downstream sessions. Sharing is admitted only by a registered qualifier. |
| `qualifier` | Conditional | — | Required when `shareable: true`; rejected otherwise. Currently registered: `context7-readonly-v3` for the `context7` key. |
| `concurrency` | No | `serial` | `serial` executes one call at a time; `parallel` permits concurrent calls within the worker. |
| `call_timeout_seconds` | No | `30` | Per-call timeout greater than 0 and no more than 3600 seconds. It does not control process idleness. |
| `idle_timeout_seconds` | Yes | — | Per-process inactivity TTL greater than 0 and no more than 86400 seconds. |
| `failure_threshold` | No | `5` | Error count from 1 through 100 that degrades a shared upstream. |
| `crash_threshold` | No | `2` | Crash count from 1 through 100 that degrades a shared upstream. |

Each spawned worker tracks its own idle timeout. A worker shuts down only when its TTL expires with no queued or active calls. Shared and session-isolated workers expire independently, and the next routed call starts a fresh process in the same effective sharing mode. A long-running call remains governed by `call_timeout_seconds`, not by the idle timeout.

Environment values are resolved from the broker process without being written into the profile, audit log, runtime report, or validation output:

```bash
export CONTEXT7_API_KEY='...'
uv run --frozen irigate --config profiles/local.yaml --check
```

While serving, Irigate watches the selected profile. Changed active upstreams must initialize successfully before routing switches. Added and changed dormant upstreams remain stopped until selected. Invalid updates leave the last valid active configuration available. Changes to `host` or `port` require restarting the broker.

## Run

Start the broker in the foreground with strict sharing admission:

```bash
uv run --frozen irigate \
  --config profiles/mvp.yaml \
  --require-qualified-sharing
```

The broker listens at `http://127.0.0.1:8765/mcp` without starting upstreams. Every MCP client URL must select tools or upstreams explicitly. Qualification, schema discovery, and process startup happen on first selected use. Each upstream's `idle_timeout_seconds` shuts down that process independently after inactivity; the next routed call starts a fresh process without changing the downstream session.

### Agent-side selection

Use exact tools for the narrowest and recommended configuration:

```text
http://127.0.0.1:8765/mcp?tools=context7__resolve-library-id,context7__query-docs
```

Select complete upstreams when the agent needs their full tool surfaces:

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

This selects only `context7`. Reverse-only selection starts from all currently configured upstreams, so profile reloads can broaden it when a new upstream is added. Prefer `tools=` for least privilege. Exactly one `tools` or `upstreams` parameter is required; repeated parameters, unknown names, malformed tokens, unrelated query parameters, and an empty result are rejected. Exact tool selection never supports `!` because excluding one tool cannot avoid starting its upstream.

An agent can combine Irigate with a directly managed MCP server:

```yaml
mcp_servers:
  irigate:
    url: "http://127.0.0.1:8765/mcp?upstreams=!code-review-graph"
  code-review-graph:
    command: code-review-graph
    args: [serve]
```

Stop the broker with `Ctrl+C`; shutdown drains active calls and closes child processes.

Strict mode rejects the first selected use of Context7 if it cannot be qualified. Omit `--require-qualified-sharing` to downgrade failed selected shared upstreams to isolated mode.

Run qualification without opening the client endpoint when diagnosing startup:

```bash
uv run --frozen irigate qualify --config profiles/mvp.yaml
```

Audit records are written as JSON lines to stderr. The default profile atomically refreshes `.irigate/runtime-report.json` with metadata-only process, reuse, timing, and failure counters.

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

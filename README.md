# Irigate

> Shared local MCP infrastructure for developers running multiple AI coding agents.

Irigate is a loopback-only MCP broker. It lets local agent sessions share explicitly qualified stdio MCP servers, reducing duplicate processes while providing metadata-only runtime reports and one audit record for every completed or rejected tool call.

## Problem hypothesis

MCP-capable coding agents commonly start stdio MCP servers as child processes. Several concurrent Hermes, Claude Code, Codex, or worker sessions can therefore start duplicate copies of the same expensive server.

A broker may improve this when:

- Several agent sessions run concurrently.
- An upstream has meaningful startup or memory cost.
- The upstream is safe to share between sessions.
- The sessions use compatible state, workspace, and credential contexts.

Sharing is not universally safe. Some MCP servers retain client-specific state, and distinct workspaces or credentials may still require separate instances. Irigate must prove the benefit per upstream rather than assuming every N×M process set can collapse to M.

## Current capabilities

- Streamable HTTP endpoint bound to `127.0.0.1`.
- Static YAML configuration loaded at startup.
- Static profiles for qualified shared and isolated stdio upstreams.
- Explicit `shareable: true` opt-in per upstream; isolated by default.
- Deterministic `<upstream-key>__<tool-name>` routing.
- Configurable serial or parallel call handling per upstream.
- Metadata-only JSON-lines telemetry: upstream, tool, duration, outcome, and error class.
- Automated compatibility and resource benchmarks for 1, 5, and 20 clients.

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
             │ static config│
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
- `profiles/` — Validated loopback-only runtime and benchmark profiles.
- `src/irigate/` — Installable package, configuration models, loader, and CLI.
- `tests/` — Executable package and runtime contracts.

## Status

- Product scope: loopback-only local MCP broker.
- Validation: Context7 is qualified for shared mode; code-review-graph remains isolated.
- Evidence: process and resident-memory consolidation is established for identical Context7 contexts. Call-latency evidence remains invalid because Context7 throttled the benchmark.
- Market evidence: hypothesis only.
- Next action: rerun the latency benchmark with adequate Context7 quota and observe normal development sessions before making a release decision.

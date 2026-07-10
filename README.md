---
title: Irigate — local MCP broker for AI coding agents
status: planning
---

# Irigate

> Shared local MCP infrastructure for developers running multiple AI coding agents.

Irigate is a proposed loopback-only MCP broker. It aims to let local agent sessions share explicitly approved stdio MCP servers, reducing duplicate processes and repeated cold starts while providing metadata-only tool-call telemetry.

The production broker is not implemented. Phase 0's bounded technical validation passed for the official Python SDK, Hermes, Kilo/OpenCode, Context7's qualified read-only surface, failure containment, and loopback Origin enforcement.

## Problem hypothesis

MCP-capable coding agents commonly start stdio MCP servers as child processes. Several concurrent Hermes, Claude Code, Codex, or worker sessions can therefore start duplicate copies of the same expensive server.

A broker may improve this when:

- Several agent sessions run concurrently.
- An upstream has meaningful startup or memory cost.
- The upstream is safe to share between sessions.
- The sessions use compatible state, workspace, and credential contexts.

Sharing is not universally safe. Some MCP servers retain client-specific state, and distinct workspaces or credentials may still require separate instances. Irigate must prove the benefit per upstream rather than assuming every N×M process set can collapse to M.

## Proposed MVP

- Streamable HTTP endpoint bound to `127.0.0.1`.
- Static YAML configuration loaded at startup.
- Two or three stdio upstreams in the validation profile.
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

## Implementation gates

Implementation follows [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md):

1. Prove Streamable HTTP round trips and multi-client correctness.
2. Prove at least one relevant, expensive stdio upstream is safe to share.
3. Build the minimal package and deterministic router.
4. Validate concurrency, shutdown, and metadata-only telemetry.
5. Benchmark realistic identical and isolated contexts.
6. Decide whether to stop, keep it as an internal utility, or release it as an open-source local broker.

If no expensive upstream is safe to share, the project stops. It does not compensate by adding unrelated security or platform features.

## Positioning

The current market hypothesis is documented in [`MARKET-RESEARCH.md`](MARKET-RESEARCH.md).

Irigate is positioned as local AI developer infrastructure, not as a competitor to enterprise control planes such as Microsoft MCP Gateway. Microsoft focuses on Kubernetes deployment, management APIs, Entra authorization, session-aware routing, and a portal. Irigate's narrower hypothesis is workstation-local stdio process consolidation across several coding-agent products.

## Repository contents

- `IMPLEMENTATION-PLAN.md` — Phased build plan, experimental gates, intended package layout, and verification.
- `MARKET-RESEARCH.md` — Honest market hypothesis, target user, Microsoft comparison, rejected positioning, and go/no-go criteria.
- `profiles/` — Pre-implementation workload examples. They are inputs to the transport and benchmark spikes, not production-ready configuration.

## Status

- Product scope: narrowed to a local MCP broker.
- Validation: Phase 0 completed; Context7 is the first qualified shared-upstream candidate, while code-review-graph remains isolated.
- Implementation: production package not started.
- Market evidence: hypothesis only.
- Next action: execute Phase 1 of `IMPLEMENTATION-PLAN.md`.

---
title: Irigate — The compliance layer for agentic coding
status: alpha
scope: MCP proxy + security middleware (Phase 1)
---

# Irigate

> The compliance layer for agentic coding.

Irigate is an enterprise governance gateway for AI agent protocols. It
multiplexes persistent backend connections across multiple agent
sessions, enforces strict compliance policies at the transport boundary,
and drastically reduces the infrastructure overhead required to scale
agentic coding.

The first release targets the **Model Context Protocol (MCP)** and
addresses two immediate problems: agent harnesses (Hermes, Claude Code,
Codex CLI, OpenCode, Cline, Kilocode, custom scripts) spawning the same
heavy MCP server subprocess per session, and the lack of any
auditable control plane between agents and backend tools. Future
releases will extend the same governance model to **OpenAI API** and
**Claude API** traffic.

## Why Irigate

Agentic coding tools are scaling from "an LLM that autocompletes" to
"an autonomous agent that calls tools, reads files, and executes
commands". That shift creates two problems for enterprise engineering
teams:

1. **Resource waste.** Each agent session currently spawns a fresh
   copy of every MCP server it talks to (DocumentDB, code-review-graph,
   context7, pencil, shadcn, Astro, DeepWiki, plus a compliance-
   hardened filesystem upstream, …). That is one subprocess per
   upstream per harness, every time, regardless of whether the
   work overlaps.
2. **No compliance checkpoint.** Every tool call goes straight from the
   agent to the backend service. There is no auditable control plane,
   no path-jail to stop a runaway `read_file` against `.env` or
   `id_rsa`, no secret scrubbing on responses, no rate limiting on
   bursty agent loops.

Irigate sits between the agent and the backend. It holds the backend
connections open once, exposes a single multiplexed endpoint to many
agents, and runs a **security middleware pipeline** around every
`tools/call` so security teams have one place to enforce policy and
audit traffic.

## Two value pillars

- **Compliance & Control.** A 7-stage security middleware pipeline runs
  around every `tools/call`: request validation, path-jail with symlink
  awareness + deny-list (blocks `.env`, `id_rsa`, `*.pem`, `.ssh/*`,
  `.git/**`), regex-based secret scrubbing on responses (AWS keys,
  GitHub tokens, PEM blocks, connection strings), sliding-window rate
  limiting, declarative per-upstream policy overrides, and a structured
  per-call audit trail (JSON-lines to stderr, args hashed not stored).
- **Resource Optimization.** Persistent, multiplexed backend
  connections replace the per-session spawn pattern. Less memory, less
  latency, fewer moving parts to operate.

## Scope of this release

This release ships **only the MCP reverse-proxy** described in
`docs/MCP-PROXY.md`. The OpenAI and Claude API governance layers are
explicitly out of scope right now; the architecture is designed to
absorb them later without breaking the MCP contract.

| Protocol          | Status     | Notes                                   |
|-------------------|------------|-----------------------------------------|
| MCP (stdio, SSE,  | spec approved | See `docs/MCP-PROXY.md` for the implementation brief. |
| streamable_http)  |            |                                         |
| OpenAI API        | planned    | Compliance + multiplexing layer TBD.    |
| Claude API        | planned    | Compliance + multiplexing layer TBD.    |

## How the MCP proxy works

The gateway — **named irigate-mcp-proxy** — is a **standalone process**
that owns its own profiles at `~/.irigate/profiles/<name>.yaml`. It does
**not** read any agent's config (`~/.hermes/...`, `~/.claude/...`,
`~/.codex/...`, etc.). At startup it loads every profile YAML, and at
request time it connects to each upstream in the selected profile as a
stdio MCP subprocess (or over SSE / streamable_http) and re-exposes the
unioned `tools/list` and `tools/call` on a single HTTP+SSE endpoint at
`http://127.0.0.1:8000/sse` with POST `/messages`. (`resources/*` is a
Phase 1 non-goal — see `docs/MCP-PROXY.md §Non-goals`.)

```
   Any MCP-aware HTTP/SSE client
   (Hermes, Claude Code, Codex, OpenCode, Cline,
    Kilocode, custom script)
        │
        │  GET  /sse?profile=<name>[&env=<key>.<var>=<value>]*
        │       (X-Profile header is an alternative to ?profile=)
        │  POST /messages?session_id=<id>
        │       (endpoint announced by SSE stream; no env override)
        ▼
┌──────────────────────────────────────────────────────────┐
│  irigate-mcp-proxy                                       │
│  ─ profiles loaded from ~/.irigate/profiles/<name>.yaml │
│  ─ security middleware (every tools/call):              │
│      request:  validate → policy → rate-limit → path-jail│
│      response: scrub-secrets → audit-log → rate-record   │
│  ─ per-upstream fork pool (TTL-based reaper)            │
│  ─ per-upstream asyncio.Lock around ClientSession       │
│  ─ bearer auth when bound non-loopback                  │
│  ─ starlette + uvicorn on 127.0.0.1:<port>              │
│  ─ PID-by-port lifecycle                                │
└──────────────────────────────────────────────────────────┘
        │
        │  middleware runs BETWEEN the agent and the upstream fork.
        │  one stdio / streamable_http client per forked instance
        ▼
   ┌─ code-review-graph (uvx stdio)
   ├─ DocumentDB       (npx stdio, env-forked per SSE session)
   ├─ context7         (npx stdio)
   ├─ pencil           (windows .exe stdio)
   ├─ shadcn           (npx stdio)
   ├─ Astro            (https streamable, pooled by outbound headers)
   ├─ DeepWiki         (https streamable, pooled by outbound headers)
   └─ fs               (python stdio; OWN deny-list + path-jail + audit;
                         gateway middleware adds a SECOND path-jail +
                         secret-scrub as defense-in-depth)
```

### Security middleware

Every inbound `tools/call` and every outbound response passes through
a 7-stage pipeline. The middleware is a direct port of the security
layer from `Donnyb369/mcp-spine` (~550 LOC across eight modules),
living in `~/.irigate/lib/irigate/security/`. Full contract:
`docs/MCP-PROXY.md §Security middleware (defense-in-depth)`.

```
agent ──► │ 1. validate_message      │
          │    (size, shape, names)  │  fail → JSON-RPC -32600 / -32602
          │ 2. resolve_effective_…   │
          │    (profile+upstream)    │
          │ 3. rate_limit.check      │  fail → JSON-RPC -32029 rate_limited
          │ 4. path_jail.check_args  │  fail → JSON-RPC -32030 / -32031
          └────────────┬─────────────┘
                       ▼ forward to upstream
          ┌────────────┴─────────────┐
          │ 5. scrub_call_tool_result│  redacts secrets in text content;
          │    (TextContent only,    │  never touches Image/Audio base64
          │     never Image/Audio)   │
          │ 6. audit_log.emit        │  JSON-line to stderr; args_hash, never args
          │ 7. rate_limit.record     │  (on success only)
          └──────────────────────────┘ ──► agent
```

| Module | What it does |
|--------|--------------|
| `validation.py` | Rejects oversized bodies, unsafe method/tool names, >100 argument keys |
| `rate_limit.py` | Sliding-window limiter: 60/min global, 30/min per-tool (configurable) |
| `paths.py` | Path-jail + deny-list with symlink awareness; `**/.env`, `**/*.pem`, `**/.ssh/**`, … |
| `secrets.py` | Scrubs AWS keys, GitHub tokens, PEM blocks, bearer tokens, connection strings from responses |
| `policy.py` | Declarative `EffectivePolicy` with per-upstream overrides |
| `commands.py` | Spawn-command allowlist (only `python3`/`node`/`npx`/`uvx`/`deno` by default) |
| `env.py` | Fail-closed `${VAR}` resolution (no silent empty-string substitution) |
| `integrity.py` | SHA-256 / HMAC helpers for audit + schema-cache keys |

**Defense-in-depth, not replacement.** The compliance-hardened `fs`
upstream keeps its own deny-list, path-jail, and audit hook (it has
full filesystem context). The gateway middleware is the second line
that catches the same threats at the transport boundary — so a
misbehaving or buggy upstream cannot silently leak.

### Key design decisions

- **Standalone, agent-agnostic.** The gateway ships as one Python binary
  plus a profiles directory. It never reads any agent's config; every
  MCP-aware HTTP/SSE client connects the same way.
- **Security middleware around every call.** A 7-stage pipeline
  (validate → policy → rate-limit → path-jail on the request;
  scrub-secrets → audit-log → rate-record on the response) runs
  inside the gateway. Profile-level `security:` block sets defaults;
  each upstream can override. Disabling the middleware globally is one
  flag (`security.enabled: false`). See
  `docs/MCP-PROXY.md §Security middleware (defense-in-depth)`.
- **Secret scrubbing is content-type aware.** The scrubber only scans
  `TextContent` and `structuredContent`, never `ImageContent` /
  `AudioContent` base64 — so vision/screenshot tools keep working while
  text-resident AWS keys / PEM blocks / connection strings are redacted.
- **Loopback by default; non-loopback requires auth.** Binds to
  `127.0.0.1` by default and rejects `0.0.0.0` / public IPs unless the
  operator passes `--allow-non-loopback` AND configures a bearer token
  (`IRIGATE_AUTH_TOKEN` or `IRIGATE_AUTH_TOKENS_FILE`). See
  `docs/MCP-PROXY.md §Network binding and auth`.
- **Per-upstream error isolation.** If one upstream fails `initialize`,
  the gateway logs a warning and continues with the rest. A single
  broken server must never prevent the remaining upstreams from
  registering.
- **Tool-name routing, no prefix.** Each upstream's tools are exposed
  under their original names (no `<key>__` prefix). Routing is by the
  JSON-RPC `params.serverKey` field (Hermes convention) when present,
  otherwise by tool-name match. Profile authors should keep tool names
  unique; if two upstreams expose the same name, the gateway uses
  first-upstream-wins (profile declaration order) and logs a warning.
- **Self-reference skip.** Any upstream entry whose URL/transport points
  at the gateway itself is dropped during profile load.
- **PID-by-port lifecycle.** `~/.irigate/logs/mcp-gateway-<port>.pid`.
  `start`, `stop`, `status`, `doctor`, `restart`, `version` mirror the
  PID-by-port daemon pattern.
- **Graceful shutdown.** SIGTERM drains in-flight tool calls (≤ 5 s),
  closes each upstream session, exits 0. SIGKILL is the last resort,
  never the default.
- **No new pip dependencies.** Reuses only `mcp`, `starlette`, `uvicorn`
  and stdlib. `yaml` is already in the runtime path.

## Quickstart

The gateway is a standalone artefact under `~/.irigate/`. Once
implemented:

```bash
# 1. Copy reference profiles into place and edit per-environment.
cp profiles/hermes-vc-gateway.yaml ~/.irigate/profiles/
cp profiles/smoke-test.yaml         ~/.irigate/profiles/
#    (edit URLs, paths, and secret names as needed)

# 2. Start the gateway (binds 127.0.0.1:8000 by default).
~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ --port 8000 start

# 3. Wire your agent. Per-agent recipes are in docs/MCP-PROXY.md
#    §AI agent setup. For Hermes Agent, add to the profile's config.yaml:
#      mcp_servers:
#        hermes:
#          url: http://localhost:8000/sse
#          transport: sse
#          headers:
#            X-Profile: hermes-vc-gateway
#          # mcp_discovery_timeout: 5   # raise if 8-upstream init is slow

# 4. Restart the agent and verify.
tail -50 ~/.hermes/profiles/<your-profile>/logs/agent.log | grep -E "MCP:"
# Expect: "MCP: registered N tool(s) from 1 server(s)" where N >= 50
# Expect NO "Expected response header Content-Type to contain 'text/event-stream'"
```

## Profile configuration

Each profile is one YAML file at `~/.irigate/profiles/<name>.yaml`.
The minimal profile lists upstreams; the security middleware is
opt-in via a top-level `security:` block. Reference profiles:
`profiles/hermes-vc-gateway.yaml`, `profiles/smoke-test.yaml`.

```yaml
name: hermes-vc-gateway
description: "Heavy MCP servers shared across the operator's agents."
upstreams:
  - key: code-review-graph
    transport: stdio
    command: uvx
    args: ["code-review-graph", "serve"]
    env: {}
    call_timeout_seconds: 30
    # Per-upstream override (precedence: upstream > profile > default).
    security:
      scrub_secrets: false          # source-code responses trip the generic key= regex
      rate_limit_overrides:
        "traverse_*": 120           # bursty graph traversals; raise from 30/min

  - key: fs
    transport: stdio
    command: python3
    args: ["-m", "irigate.mcp_filesystem"]
    env: {}
    fs:                              # opaque to the gateway; passed via $IRIGATE_UPSTREAM_CONFIG
      allowed_roots: ["${HERMES_KANBAN_WORKSPACE}"]
      max_file_size_mb: 10
      read_only: true
    call_timeout_seconds: 15

# Profile-level security defaults (apply to every upstream unless overridden).
security:
  enabled: true
  scrub_secrets_in_responses: true
  scrub_secrets_in_logs: true
  audit_all_tool_calls: true
  max_message_size: 10485760        # 10 MB
  rate_limit_enabled: true
  global_rate_limit: 60             # calls per 60s across all upstreams
  per_tool_rate_limit: 30           # calls per 60s per (upstream, tool)
  rate_limit_overrides: {}
  path_jail_enabled: true
  path:
    allowed_roots: []               # empty = gateway jail is a no-op; fs upstream's own jail still applies
    denied_patterns_extra: []       # adds to the 18 default deny-list patterns
    allow_override: []              # explicit per-pattern opt-out from defaults
```

Full `security:` schema, per-upstream precedence rules, and the
default deny-list (`.env`, `*.pem`, `id_rsa`, `.ssh/**`, `.git/**`, …):
`docs/MCP-PROXY.md §Security middleware (defense-in-depth)`.

## Lifecycle CLI

```
irigate_mcp_proxy.py [--profiles-dir DIR] [--host 127.0.0.1] [--port 8000]
                     [--log-level INFO]
                     <command>
```

| Command              | Behaviour                                                |
|----------------------|----------------------------------------------------------|
| `start [--foreground]`| Daemonize by default, foreground if `--foreground`. Foreground stays attached to the terminal and writes no PID file. Preflight (`doctor`) runs unless `--skip-checks` is set. |
| `stop`               | SIGTERM via PID file; exit 0 when stopped or no PID, exit 2 on partial failure. |
| `status`             | Print running PID + URL + log path + loaded profile count or "not running". |
| `doctor`             | Run preflight checks standalone (no daemon).             |
| `restart`            | `stop`; `start`.                                         |
| `version`            | Print the gateway version constant and exit.             |

Defaults: `--profiles-dir ~/.irigate/profiles/`, `--host 127.0.0.1`, `--port 8000`. Running no subcommand defaults to `start --foreground`.

## Verification

See `docs/MCP-PROXY.md §Verification` for the full checklist (25 steps).
Summary:

1. Gateway binds `127.0.0.1:8000`.
2. `/sse` returns `text/event-stream` (not `text/html`).
3. `/messages` accepts `initialize` and returns
   `serverInfo.name="irigate-mcp-proxy"`.
4. `/profiles` lists available profiles (no secret content).
5. Agent discovers the gateway and registers the unioned upstream tools.
6. End-to-end tool call from an agent hits an upstream.
7. Killing one upstream's fork leaves the other upstreams serving.
8. SIGTERM is graceful within 5 s.
9. `doctor` reports per-upstream status without refusing to start.
10. `fs` upstream deny-list + path-jail (`.env`, `id_rsa`, symlink
    escape, path traversal, null byte) enforced end-to-end.
11. Security middleware path-jail blocks external paths and symlink
    escapes at the transport boundary (defense-in-depth on top of the
    `fs` upstream's own jail).
12. Security middleware secret scrubbing redacts AWS keys, GitHub
    tokens, connection strings, PEM blocks, and bearer tokens from
    text responses; original values do NOT appear in the stderr log.
13. Security middleware rate limiting returns JSON-RPC `-32029
    rate_limited` when a per-tool bucket is exceeded.

## Rollback

The gateway is non-invasive — rollback is one stop plus one hand-edit
per agent:

```bash
~/.irigate/bin/irigate_mcp_proxy.py --port 8000 stop
```

Then remove the `mcpServers` entry you added to each agent. Full
rollback steps are in `docs/MCP-PROXY.md §Rollback`.

## Documentation

- `docs/MCP-PROXY.md` — Full implementation spec for the MCP
  reverse-proxy + security middleware (problem, design, the 7-stage
  middleware pipeline, lifecycle, verification, rollback, open
  questions). This is the authoritative spec; this README is a
  summary.
- `docs/initial_chat.txt` — Origin conversation: the
  multiplexer-problem framing, naming exploration, and tagline
  selection.
- `docs/AGENTS.md` — Conventions for files in this `docs/` folder
  (spec shape, status lifecycle, verification discipline).
- `profiles/hermes-vc-gateway.yaml`,
  `profiles/smoke-test.yaml` — Reference profile YAMLs the operator
  copies into `~/.irigate/profiles/` and edits per-environment. The
  `hermes-vc-gateway` profile demonstrates the `security:` block and
  a per-upstream override.

## Roadmap

- **Phase 1 — MCP reverse-proxy + security middleware.** Implement the
  SSE multiplexer described in `docs/MCP-PROXY.md`. Bind
  127.0.0.1:8000; eight upstream servers (see §Filesystem upstream for
  the compliance-hardened fs entry). PID-by-port lifecycle. The 7-stage
  security middleware (path-jail, secret scrubbing, rate limiting,
  audit trail) ships in the same release as a defense-in-depth layer
  between agents and upstreams.
- **Phase 2 — OpenAI API governance.** Extend the same multiplexer
  + compliance-checkpoint model to OpenAI-compatible `/v1/chat/
  completions` traffic. Audit hooks for prompt/response inspection,
  role-based access on tool calls, rate limiting.
- **Phase 3 — Claude API governance.** Mirror Phase 2 for the
  Anthropic Messages API. Share the compliance policy format with
  Phase 2 so operators write one rule file.
- **Phase 4 — Unified, tamper-proof audit log.** The middleware
  already emits per-call JSON-lines records to stderr (stage 6).
  Phase 4 adds an HMAC key (`IRIGATE_AUDIT_HMAC_KEY`) for tamper-
  proof records, an append-only file sink, and a queryable format
  (SQLite/Parquet) consumable by SIEM tooling — across MCP, OpenAI,
  and Claude traffic.

The compliance policy format and audit record shape are the same
across phases so that an operator's investment in Phase 1 carries
forward.

## Out of scope

Irigate's middleware adopts the security layer of
`Donnyb369/mcp-spine` (request validation, path-jail, secret
scrubbing, rate limiting, declarative policy, spawn-command guard,
fail-closed env resolution, audit hashing). The following features
from the two reference projects are **deliberately skipped** —
recorded here so a future contributor does not re-add them by
accident. The split criterion is simple: would this feature make
sense for an upstream that has nothing to do with the filesystem
(e.g. DocumentDB, pencil)? If yes, it is a candidate for the
gateway; if no, it belongs in the upstream.

**From `Donnyb369/mcp-spine`, skipped:**

| Feature | Why out of scope |
|---------|------------------|
| ChromaDB-backed semantic tool routing | Pushes the gateway toward an LLM-in-the-loop router; the gateway stays a transport broker. |
| Schema minification | Gateway forwards tool schemas verbatim so the agent sees the upstream's real contract; rewriting schemas breaks agents that pattern-match on field names. |
| SHA-256 file state guard | Filesystem-mutation-specific; belongs in the fs upstream, not the gateway. |
| Token budget tracking | Gateway does not meter LLM tokens, only MCP calls. |
| Plugin hook system (`on_tool_call` / `on_tool_response`) | Plugin composition is a Phase 2+ extension; Phase 1 keeps the gateway single-responsibility. |
| Prompt-injection detection on tool responses | Gateway stays opaque to tool content; injection detection is the agent's job. |
| Tool-response LRU cache | Caching is upstream-specific (each upstream has its own cache-key semantics). |
| Webhook notifications | Operator UX, not a gateway concern. |
| HMAC-fingerprinted audit log | Gateway's stderr JSON-lines log is the Phase 1 audit surface; HMAC chaining is Phase 2 (see Roadmap). |
| Web dashboard | Operator UX, not a gateway concern. |
| Config hot-reload | Gateway restarts on profile changes; hot-reload is a future enhancement. |

**From `EdibleTuber/mcp-server` (Void editor filesystem), skipped:**

| Feature | Why out of scope |
|---------|------------------|
| Hash-based backup/undo | Filesystem-mutation-specific; belongs in the fs upstream. |
| Auto-commit git integration | Filesystem-specific; belongs in the fs upstream. |
| Multi-user support | Single-tenant workstation deployment; Phase 2+ if needed. |
| Dry-run mode | Operator UX; lives in the upstream CLI surface, not the gateway. |
| Hardcoded extension allow-list in the gateway | The extension allow-list and read-only flag are part of the upstream's own config block (the `fs:` profile key), not a gateway concern. |

Full rationale and the "adopted vs. skipped" split:
`docs/MCP-PROXY.md §Non-goals` (Features deliberately skipped from the
reference projects).

## Status

- Spec: `docs/MCP-PROXY.md` (`status: approved`).
- Implementation: not started. The gateway will live at
  `~/.irigate/bin/irigate_mcp_proxy.py` per the spec; this repo
  currently holds only the spec, the reference profiles, and the
  originating conversation.

## Origin

The name **Irigate** comes from Iris — the Greek goddess of the
rainbow and the messenger of the Olympian gods — combined with
"gate" to emphasize the control and checkpoint nature of the
software. The metaphor fits: the proxy is the gate through which all
AI agent API traffic must pass to be audited and controlled.

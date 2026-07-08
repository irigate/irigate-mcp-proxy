---
title: Irigate MCP gateway — multi-profile SSE multiplexer with per-upstream env forking, tenant forwarding, compliance-hardened filesystem upstream, and spine-derived security middleware
status: approved
target: ~/.irigate/bin/irigate_mcp_proxy.py
created: 2026-07-06
updated: 2026-07-08
session_id: 20260706_201000_irigate
amendment_session: 20260708_spine_integration
amendments: |
  - 2026-07-08 (tenant_forwarding): X-Tenant + X-Kanban-Workspace
    headers; tenants: profile allowlist; HERMES_TENANT /
    HERMES_KANBAN_WORKSPACE forwarding to upstream forks.
  - 2026-07-08 (filesystem_upstream): add an 8th upstream,
    `filesystem` (key `fs`), to the hermes-vc-gateway profile. The
    upstream is a compliance-hardened filesystem MCP server that ships
    with its own deny-list (.env, .key, .pem, .ssh, id_rsa), path-jail
    with symlink awareness, and a structured audit hook. The gateway
    itself does NOT enforce these checks; the upstream does. The
    gateway's role is to (a) treat the upstream like any other
    stdio upstream (fork pool, TTL reaper, per-call lock, env
    forwarding), (b) document the deny-list as an upstream contract
    in §Filesystem upstream (compliance-hardened), (c) add a
    verification step that proves the deny-list works end-to-end.
    Phase 1 Non-goals (rate-limiting, per-user authz, gateway-side
    policy enforcement) are unchanged.
  - 2026-07-08 (spine_integration): adopt the security layer of
    `Donnyb369/mcp-spine` into the gateway as in-process middleware
    — request validation, path jail with symlink awareness +
    deny-list, regex-based secret scrubbing (content-type aware),
    sliding-window rate limiting, declarative security policy
    with per-upstream overrides, spawn-command allowlist, fail-
    closed `${VAR}` resolution, and SHA-256/HMAC hashing helpers.
    The eight modules (`validation.py`, `rate_limit.py`,
    `paths.py`, `secrets.py`, `policy.py`, `commands.py`,
    `env.py`, `integrity.py`, ~550 LOC combined) are ported
    into `~/.irigate/lib/irigate/security/`. The middleware runs
    a fixed 7-stage pipeline around every `tools/call`
    (§Security middleware → Middleware call pipeline). The
    §Filesystem upstream (compliance-hardened) is unchanged but
    its role shifts to "authoritative enforcement"; the gateway
    middleware is now defense-in-depth and ALSO refuses `.env` /
    `id_rsa` / symlink escapes at the transport boundary, so a
    misbehaving or buggy upstream cannot silently leak. The
    profile gains an optional `security:` block (profile-level
    defaults + per-upstream overrides); defaults match spine's
    defaults where they apply.
    Adopted: request validation, path jail, secret scrubbing,
    rate limiting, declarative policy, per-tool policy hooks,
    spawn-command guard, fail-closed env resolution, audit
    hashing. Still out of scope: ChromaDB-backed semantic tool
    routing, schema minification, SHA-256 file state guard,
    token budget tracking, plugin hook system, prompt-injection
    detection on tool responses, tool-response LRU cache,
    webhook notifications, HMAC-fingerprinted audit log, web
    dashboard, config hot-reload. The split criterion is
    unchanged: upstream-agnostic security features go in the
    gateway; upstream-specific or UX-only features stay with
    the upstream. Per the user's §Future enhancements removal
    rule, the spec no longer lists the adopted features in
    §Future enhancements (Phase 2+); only the still-skipped
    features remain.
supersedes: 20260705_105103_e1dfa4
---

## Problem

MCP-aware AI agents (Claude Code, Codex CLI, OpenCode, Cline,
Kilocode, Hermes Agent, custom scripts) each spawn their own copy
of every MCP server they talk to. An operator running five agents
that all need DocumentDB ends up with five `npx
awslabs.documentdb-mcp-server` subprocesses on the host — one per
agent — even though they all connect to the same backend.

That is wasted memory, wasted startup latency, and a duplicated
process-management surface (each agent has its own subprocess
lifecycle, its own retry loop, its own crash recovery). For
upstreams with expensive cold starts (DocumentDB ~2 s, pencil ~3 s,
Astro's MCP server ~1.5 s) the cost compounds: every agent
restart pays the full cold-start penalty.

The gateway solves this by holding one shared copy of each
upstream and re-exposing its `tools/list` and `tools/call` on a
single HTTP/SSE endpoint. Every agent that points at the gateway
shares the same upstream pool, pays the cold-start cost once per
TTL window, and declares one `mcpServers` entry instead of one
per upstream.

(`resources/*` is out of scope for Phase 1 — see §Non-goals. The
gateway proxies `tools/list` and `tools/call` only; a future revision
may add `resources/list` / `resources/read` routing.)

### Why this is a standalone project

The gateway owns its profiles, lifecycle, configuration, and
runtime. It does not depend on any agent's config schema, any
agent's profile-resolution code, or any agent's CLI surface.
This is deliberate:

* **Per-agent isolation.** A regression in the gateway's profile
  loader cannot break an agent's own config. An agent upgrade
  cannot break the gateway's profile parsing.
* **Single-responsibility deployment.** The gateway ships as one
  Python binary plus a profiles directory. An operator can install
  it without installing any agent, and vice versa.
* **Cross-agent compatibility.** Every MCP-aware HTTP/SSE client
  (current and future) connects the same way: standard MCP-over-SSE,
  `X-Profile` header or `?profile=` query, bearer auth when bound
  non-loopback. No per-agent adapter is needed.

The gateway lives at `~/.irigate/bin/irigate_mcp_proxy.py` and
its profiles at `~/.irigate/profiles/<name>.yaml` — outside any
agent's home directory. Operators wire an agent to the gateway
by adding one `mcpServers` entry to the agent's own config (see
§AI agent setup for per-agent recipes).

## Goal

Add a standalone SSE MCP gateway process — **named irigate-mcp-proxy** —
that:

1. Owns its own profiles at `~/.irigate/profiles/<name>.yaml`. The
   gateway never reads any agent's config (`~/.hermes/...`,
   `~/.claude/...`, `~/.codex/...`, etc.).
2. At startup, loads every profile YAML in the configured
   profiles dir. Each profile is a named set of upstream MCP server
   entries (stdio, sse, or streamable_http).
3. Re-exposes every profile's unioned `tools/list` and `tools/call`
   on a single HTTP+SSE endpoint at
   `http://<host>:<port>/sse?profile=<name>`. The SSE stream announces
   the session-specific POST endpoint `/messages?session_id=<id>`;
   clients MUST post JSON-RPC requests to that endpoint. `X-Profile`
   header is an alternative to the `?profile=` query parameter on the
   initial `/sse` request. (`resources/*` is a Phase 1 non-goal.)
4. Accepts per-upstream env overrides at SSE connection time via
   `?env=<upstream-key>.<VAR-NAME>=<value>`. For stdio upstreams the
   override selects a separate subprocess fork keyed by env
   fingerprint; for HTTP upstreams it selects a separate HTTP client
   session keyed by outbound-header fingerprint. Other upstreams in
   the profile keep sharing their existing pooled instances.
5. Accepts tenant-scoped profile resolution via `?tenant=<value>` /
   `X-Tenant: <value>`, where each profile declares an optional
   `tenants:` allowlist. A profile with no `tenants:` is valid for
   all tenants (legacy behaviour). When the header is present, the
   gateway additionally forwards the matching Hermes Kanban worker
   env vars (`HERMES_TENANT`, `HERMES_KANBAN_WORKSPACE`) into the
   spawned upstream's environment / outbound headers. See
   §Tenant forwarding.
6. Is callable from any MCP-aware HTTP/SSE client (Hermes, Claude
   Code, Codex, OpenCode, Cline, Kilocode, custom script) by
   pointing at the URL with the desired `?profile=` parameter or
   `X-Profile` header.
7. Runs many parallel sessions without one upstream blocking another.
   Per-upstream `asyncio.Lock` around `ClientSession.call_tool`;
   TTL-based reaper tears down idle forks; per-call timeout.
8. Binds loopback by default and refuses to start on a non-loopback
   address without both `--allow-non-loopback` opt-in AND a
   configured bearer token (`IRIGATE_AUTH_TOKEN` or
   `IRIGATE_AUTH_TOKENS_FILE`). Authenticated deployments can run
   on the LAN or behind a reverse proxy. See §Network binding and
   auth for the full model.

End state:

* Every agent configured to point at the gateway sees the unioned
  upstream tools without spawning its own subprocesses.
* `?profile=` switches an agent's upstream set at SSE-session creation
  time without restarting the gateway.
* Per-call environment overrides let a single profile expose
  different credentials to different SSE sessions without restarting
  the gateway. Example: an agent testing a new MongoDB cluster passes
  `?env=DocumentDB.DOCUMENTDB_CONNECTION_STRING=***` on the initial
  `/sse` connection; the gateway forks only that upstream for the
  session while the other upstreams in the profile stay shared.

The gateway's default port is **8000**; loopback-only by default;
non-loopback opt-in via `--allow-non-loopback` + bearer auth. Multiple
ports are allowed; each port runs its own daemon.

## Non-goals

* Replacing any agent's MCP discovery loop. The gateway speaks
  standard MCP over SSE; every agent talks to it as it would any
  SSE MCP server.
* `resources/*` proxying. Phase 1 implements `tools/list` and
  `tools/call` only. The gateway responds to `resources/list` and
  `resources/read` with a JSON-RPC error (`method not found`) so a
  client that probes capabilities does not hang or 404; it simply
  sees an empty resources capability. A future revision may add
  resource routing.
* OAuth, per-user authorization, and rate-limiting. The gateway
  implements shared bearer-token auth sufficient for LAN deployments;
  OAuth, per-user authz, and rate limiting are out of scope.
* Dynamic reload of gateway profiles. Profiles are read at startup.
  Restart the gateway to pick up changes.
* Proxying the `mcp_servers.hermes` entry in the gateway's own
  profiles if it ever points at the gateway itself (skip
  self-references).
* Per-client profile isolation. All clients with a valid bearer
  token get the same profile set. Per-client routing requires
  issuing different tokens and pointing each client at a different
  profile (or running multiple gateway instances on different
  ports) — out of scope.
* Cross-upstream env override. A `&env=DocumentDB.API_KEY=***`
  setting does not bleed into code-review-graph's env. Per-upstream
  pooled instance (stdio fork or HTTP session) is the unit.
* Hot forking under load. The fork pool is bounded by TTL
  with a hard cap of `MAX_FORKED_INSTANCES_PER_UPSTREAM = 16`
  per upstream key; further unique env fingerprints return
  `429 Too Many Forks` rather than spawning unbounded subprocesses.
* **Gateway-side policy enforcement on tool-call arguments or
  responses — partial.** The §Security middleware
  (defense-in-depth) section DOES inspect tool-call arguments
  for sensitive paths (path-jail + deny-list against `arguments`
  that look like file paths) and DOES scrub a small set of
  well-known secret patterns (`security/secrets.py` regex set)
  from `tools/call` responses before they reach the agent. These
  two are gateway-portable and the spec adopts them from
  `Donnyb369/mcp-spine`. The gateway does NOT inspect responses
  for prompt-injection content, does NOT enforce per-tenant
  data isolation by inspecting tool arguments, and does NOT
  implement a generic upstream-agnostic deny-list DSL — the
  deny-list and the prompt-injection detection are deliberately
  narrow so the gateway stays a transport broker. Future
  revisions may add a generic policy DSL (Phase 2+); the
  current spec keeps the surface minimal.
* Persisting call-time env overrides to disk. The fork lives only for
  the duration of the SSE session.
* Multi-tenant data isolation beyond (a) per-profile `tenants:`
  allowlist on inbound routing and (b) per-fork `HERMES_TENANT` /
  `HERMES_KANBAN_WORKSPACE` separation in the subprocess env. A
  tenant's data path must be enforced by the upstream itself (e.g.
  DocumentDB using a connection string that scopes by tenant DB,
  filesystem MCP servers honouring `$HERMES_KANBAN_WORKSPACE` as
  cwd). The gateway never inspects upstream responses to enforce
  tenant boundaries; it cannot, since MCP tool calls are
  opaque JSON-RPC payloads.
* **Features deliberately skipped from the reference projects.**
  The `fs` upstream's deny-list + path-jail + audit model is
  inspired by two existing projects, and the gateway-side
  security middleware (see §Security middleware
  (defense-in-depth)) ports the security-layer modules of
  `Donnyb369/mcp-spine` directly. To prevent scope drift, the
  following features from those projects are EXPLICITLY out of
  scope for this spec (and recorded here so a future contributor
  does not re-add them by accident):
  - **Adopted from `Donnyb369/mcp-spine`** (see
    §Security middleware (defense-in-depth) for the full
    contract): path jail with symlink awareness
    (`security/paths.py`), regex-based secret scrubbing
    (`security/secrets.py`), sliding-window rate limiting
    (`security/rate_limit.py`), declarative security policy
    (`security/policy.py`) including per-tool deny/audit/
    rate-override hooks, a default path deny-list matching
    spine's defaults (`.env`, `.env.*`, `secrets.*`, `*.pem`,
    `*.key`, `id_rsa*`, `.ssh/*`, `.aws/*`, `.gnupg/*`),
    and a `?env=` denylist for `*_SECRET` / `_TOKEN` /
    `_API_KEY` var names. The spine features that *remain*
    out of scope are listed next.
  - **Still out of scope from `Donnyb369/mcp-spine`**:

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
    | HMAC-fingerprinted audit log | Gateway's stderr JSON-lines log is the Phase 1 audit surface; HMAC chaining is Phase 2 (see §Future enhancements). |
    | Web dashboard | Operator UX, not a gateway concern. |
    | Config hot-reload | Gateway restarts on profile changes; hot-reload is a §Future enhancement. |

  - **From `EdibleTuber/mcp-server` (Void editor filesystem)**, still
    skipped: hash-based backup/undo (filesystem-mutation-specific),
    auto-commit git integration (filesystem-specific), multi-user
    support (single-tenant workstation deployment), dry-run mode
    (operator UX), hardcoded extension allow-list in the gateway
    (the extension allow-list and read-only flag are part of the
    upstream's own config block — the `fs:` profile key, not a
    gateway concern).
  The spec's test for "should this be in the gateway" is
  simple: would this feature make sense for an upstream that
  has nothing to do with the filesystem (e.g. DocumentDB,
  pencil)? If yes, it is a candidate for the gateway; if no,
  it belongs in the upstream. Every feature in the still-out-
  of-scope list above is either upstream-specific or operator
  UX, not gateway-portable.

## Constraints

* **Bind to loopback by default; non-loopback requires auth.** Public
  exposure is a security concern for the workstation deployment
  (code-review-graph has no auth; DocumentDB inherits the local
  MongoDB connection). The default `--host` is `127.0.0.1`; the
  gateway rejects `0.0.0.0` and unspecified addresses by default
  with a clear error referencing this spec's loopback-by-default
  constraint. When `--allow-non-loopback` is set, the gateway
  accepts any bind address but requires a bearer token
  (`IRIGATE_AUTH_TOKEN` or `IRIGATE_AUTH_TOKENS_FILE`). See
  §Network binding and auth for the full model.
* **No new pip dependencies.** Use only `mcp`, `starlette`, `uvicorn`
  (all already in the runtime venv) and stdlib (`asyncio`, `logging`,
  `signal`, `argparse`, `pathlib`, `subprocess`, `json`, `threading`,
  `hashlib`). `yaml` is in the runtime path via PyYAML (already a
  standard dependency in any Python runtime that includes the `mcp`
  SDK's transitive deps).
  **Pinned combination** (verified against the runtime venv at spec
  approval time): `mcp == 1.27.1`, `starlette >= 0.40`, `uvicorn >=
  0.30`, Python 3.11+. The implementer MUST use the exact import names
  available in mcp 1.27.1:
  - `mcp.server.sse.SseServerTransport` (server-side SSE)
  - `mcp.server.fastmcp.FastMCP` *or* `mcp.server.Server` (server core)
  - `mcp.client.sse.sse_client` (client SSE)
  - `mcp.client.streamable_http.streamablehttp_client` (client
    streamable HTTP — note the name: `streamablehttp_client`, NOT
    `streamable_http_client`)
  - `mcp.client.stdio.stdio_client` + `StdioServerParameters`
  - `mcp.ClientSession`
  - `mcp.types.LATEST_PROTOCOL_VERSION` (currently `2025-11-25`)
  **Transport round-trip pre-check (mandatory).** Before building any
  routing logic, the implementer MUST write a ~40-line spike that:
  (a) starts the gateway's SSE app on a random loopback port;
  (b) connects an `mcp.client.sse.sse_client` to `/sse`;
  (c) completes `initialize` + `tools/list` against a single stdio
      upstream (the smoke-test echo);
  (d) asserts `serverInfo.name == "irigate-mcp-proxy"` and a non-empty
      tool list.
  This spike proves the `SseServerTransport` ↔ `sse_client` framing
  pair agrees under the pinned version. If it fails, the implementer
  stops and reports the exact mcp version + error before proceeding —
  do NOT paper over a transport mismatch by swapping framing by hand.
  The SSE transport (`SseServerTransport`) is being deprecated upstream
  in favour of Streamable HTTP; Phase 1 ships SSE because every
  documented agent speaks it today, but the implementer should isolate
  the transport pair behind one function so a future migration is a
  single-file change.
* **No agent-config dependency.** The gateway never imports any
  agent's code and never reads any agent's config file. Profile
  resolution is gateway-internal: a list of YAML files in
  `--profiles-dir` (default `~/.irigate/profiles/`), each top-level
  file is one profile keyed by filename minus `.yaml`.
* **stderr-only logging.** stderr is the operator-visible log
  channel; stdout is reserved for data. Format:
  `%(asctime)s [%(levelname)s] %(name)s: %(message)s`, matching
  Hermes' own convention.
* **Graceful shutdown on SIGTERM/SIGINT.** Drain in-flight tool
  calls (max `GRACEFUL_TIMEOUT_SECONDS = 5.0`), close every forked
  upstream session, exit 0. SIGKILL must be the last resort, never
  the default.
* **Per-upstream error isolation.** If one upstream server fails
  `initialize`, log it and continue with the rest. A single broken
  server must not prevent the gateway from registering the others.
* **env-var name declarations only.** The gateway profile's
  `upstreams[i].env:` block declares `<VAR-NAME>: <description>` pairs
  for the upstream. **Never defaults.** Defaults hide the fact that
  an env var is expected and lead to operators hitting stale creds.
  Callers who do not override the declared vars get the inherited OS
  env (filtered by `upstreams[i].inherit_os_env:`).
* **env override namespace.** `&env=<upstream-key>.<VAR-NAME>=<value>`.
  The prefix `<upstream-key>` must match an upstream key in the
  resolved profile; `<VAR-NAME>` must match a declared name in that
  upstream's `env:` block. Unknown keys or names are rejected with
  HTTP 400 and a clear error listing the accepted pairs (sourced
  from `GET /profiles/<name>/schema`).
* **Per-upstream pooled instance, not per-profile fork.** A `&env=`
  override on one upstream in a profile must not spawn/recreate
  instances for the others. Stdio upstreams have fork pools keyed by
  env-fingerprint; HTTP upstreams have client-session pools keyed by
  header-fingerprint.
* **Fork pool bounded by TTL with a hard cap backstop.** Each
  upstream declares its own `ttl_seconds` (default 300). The gateway
  reaps forks whose `last_used_at` is older than `ttl_seconds`
  via a single shared background asyncio task; forks still in
  flight are never reaped. A hard cap of
  `MAX_FORKED_INSTANCES_PER_UPSTREAM = 16` is the emergency brake:
  further unique env fingerprints return `429 Too Many Forks` with
  `Retry-After: <ttl_seconds>` and a stderr log naming the upstream
  key.
* **Tool-name routing.** Each upstream's tools are exposed under
  their original upstream names (no `<key>__` prefix). There are two
  routing modes:
  - **`params.serverKey` (Hermes convention).** If the JSON-RPC
    `tools/call` request carries `params.serverKey`, the gateway
    routes directly to that upstream. This field is non-standard MCP;
    **only Hermes sends it.** Claude Code, Codex, OpenCode, Cline,
    Kilocode, and custom clients never set it, so for 5 of the 6
    documented agents the gateway always falls through to tool-name
    match.
  - **Tool-name match (default for every non-Hermes client).** The
    gateway resolves `params.name` against an upstream→tool-name map
    built at `tools/list` time.
  Because tool-name match is the common path, **the operator's
  profiles SHOULD declare upstreams whose tool names are globally
  unique within the profile.** When two upstreams in the same profile
  expose the same tool name, the gateway applies a deterministic
  tiebreak: **first-upstream-wins** (profile declaration order), emits
  a `WARNING` to stderr naming both upstreams and the colliding tool,
  and returns the result from the first upstream. This is preferred
  over a hard 4xx `RouteAmbiguous` because a hard error would brick
  that tool for every non-Hermes client (i.e. 5 of 6 documented
  agents), which is worse than a deterministic-but-arbitrary route.
  `serverKey` routing, when present, bypasses the map entirely and is
  never ambiguous.
* **Skip self-references by name.** Any `mcp_servers.<name>` entry
  whose URL/transport points at the gateway itself (loopback on the
  configured `--host:--port`) is dropped during profile load. This
  prevents the gateway from proxying itself if an operator copies a
  gateway-pointing entry from one of their agents into a gateway
  profile.
* **Tenant scoping is explicit and per-profile.** Tenants are a
  request-time concept (matching Hermes Kanban's
  `$HERMES_TENANT`, documented at
  <https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban>);
  the gateway treats them as an allowlist on each profile.
  * `tenants:` (optional list of strings) on a profile entry lists
    the `X-Tenant` header values the profile accepts. A profile with
    no `tenants:` key is valid for all tenants (legacy behaviour).
  * On `GET /sse`, the gateway reads `X-Tenant:` (or `?tenant=` query)
    and resolves a profile whose `tenants:` list either contains the
    value OR is empty. A profile whose list is non-empty and does
    NOT contain the value is rejected with HTTP 403 listing the
    profiles that DO accept the value at `/profiles` (no secret
    content). When both query and header disagree, the query wins
    (matches the `?profile=` precedence).
  * When the request omits both `?tenant=` and `X-Tenant:`, the
    gateway performs NO tenant check: every profile is reachable
    regardless of its `tenants:` list (legacy wildcard behaviour).
    Tenant scoping requires the caller to opt in by sending the
    header. This keeps headerless clients (Claude Code, Codex,
    OpenCode, custom scripts) working against the gateway without
    modification.
  * The Kanban dispatcher (`kanban.dispatch_in_gateway: true`) sets
    `HERMES_TENANT` in the worker subprocess env; to forward that
    through the gateway to upstream MCP servers the spawn-time hook
    adds `X-Tenant: <value>` to the outbound `/sse` request. See
    §Tenant forwarding below for how the gateway turns the inbound
    header into the env vars and outbound headers the upstream
    receives.
* **`$HERMES_KANBAN_WORKSPACE` is forwarded alongside tenant.** The
  Kanban dispatcher also sets `HERMES_KANBAN_WORKSPACE=<abs-path>` on
  every spawned worker — this is the working directory the worker
  `cd`s into (per the worker-lifecycle guidance in the Kanban docs).
  Operators wire this through the gateway by sending the
  `X-Kanban-Workspace: <abs-path>` header on `/sse`; the gateway
  injects it into stdio subprocess env verbatim and forwards it as
  an outbound HTTP header on streamable_http upstreams. The header
  is only meaningful for upstream servers that operate on the
  filesystem (filesystem- or git-based MCP servers — code-review-
  graph, custom git MCPs); the gateway forwards it unconditionally
  (the upstream ignores it if it does not care), so callers do not
  have to know which upstreams need it. Paths are validated as
  absolute (any path not starting with `/` is rejected with 400 so
  relative-path confusion cannot reach subprocess cwd); see §Tenant
  forwarding.
* **Match the gateway's fingerprint across releases.** The JSON-RPC
  `initialize` response advertises
  `serverInfo.name="irigate-mcp-proxy"`. The advertised protocol
  version follows `mcp.types.LATEST_PROTOCOL_VERSION` from the pinned
  `mcp` SDK (currently `2025-11-25`); it is NOT hard-coded to a
  constant, so a future mcp SDK bump updates it automatically. The
  server name is the stable fingerprint across releases so debug logs
  keep identifying the gateway.
* **Profile resolution precedence.** `?profile=<name>` and
  `X-Profile: <name>` are both accepted. If both are present and
  disagree, the query parameter wins (it's the most explicit). If
  neither is present, return HTTP 400 with a list of available
  profiles (no secret content).
* **env override scope is the SSE session.** `?env=` is read on
  `/sse` and applied for the entire session. `POST /messages` rejects
  `?env=` or `X-Env-*` headers with HTTP 400 — the override must be
  re-established by reconnecting to `/sse`. This prevents a mid-
  session pivot to a different upstream's env dict.
* **`/healthz` requires auth by default.** When the gateway is bound
  to a non-loopback address and bearer auth is configured,
  `GET /healthz` requires the same bearer token as `/sse` and
  `/messages`. Operators who need an unauthenticated liveness probe
  (e.g. a Prometheus blackbox-exporter, a k8s liveness/readiness
  probe, a sidecar health checker that cannot present credentials)
  set `IRIGATE_HEALTHZ_PUBLIC=true`. The body returned by `/healthz`
  is identical in both modes (`{"status":"ok","upstreams":N,
  "forks":M,"port":<port>}`); only the auth requirement changes.
  The `/healthz` body discloses fork count and upstream count, which
  is operationally useful but not sensitive; the auth requirement
  exists to prevent unauthenticated network observers from probing
  the gateway's runtime state.

## Design

### Port allocation

The default port is **8000**. This matches Hermes' documented Graphiti
MCP example URL at `hermes_cli/profile_distribution.py:44` and is
the URL every agent's `mcpServers` entry is already configured for.
Multiple ports are allowed: each gateway instance has its own PID
file keyed by port (`~/.irigate/logs/mcp-gateway-<port>.pid`), its
own log file, and its own profile directory pointer. Two gateways
on different ports do not share fork pools (intentional — different
ports typically serve different trust boundaries: e.g. a smoke-test
runner on 8002 while a Hermes profile holds 8000).

`kill $(cat ~/.irigate/logs/mcp-gateway-<port>.pid)` is the
canonical way to stop a gateway instance without resorting to
`pkill -f`. The PID-by-port pattern matches what
`hermes-bridge`'s `cli.py` already does; the gateway implements
its own copy of the same idiom rather than importing it.

### What was considered

1. **`hermes mcp serve --port 8000`** — rejected; the subcommand has
   no `--port` flag and goes the opposite direction (Hermes-as-server,
   not Hermes-as-client-of-gateway).
2. **Patch the Hermes dashboard to also serve MCP** — rejected; the
   dashboard is a FastAPI app for the React SPA, and layering MCP
   routes onto it would couple unrelated lifecycles.
3. **Spawn the upstreams directly inside each agent** — rejected;
   the whole point of the gateway is to avoid per-agent subprocess
   duplication, and this would also double-spawn when multiple agents
   are running.
4. **A small dedicated gateway script** — chosen. Reads profiles
   once, mounts one starlette SSE app on the chosen port, fans every
   incoming request out to the matching upstream by JSON-RPC
   `params.serverKey` (Hermes convention) or by upstream-tool map
   match (fallback).
5. **Reuse code from `hermes-bridge`**
   (`~/src/rb/jcnh74-hermes-bridge/`) — rejected for the MCP core
   (zero overlap), accepted for lifecycle ergonomics (four patterns
   copied as idioms, not as imports).
6. **Per-profile fork semantics** — rejected. The fork unit is the
   upstream, not the profile; an `?env=` override on one upstream
   in a profile must not spawn a fresh fork for the others.
7. **Multi-port default.** Multiple ports are allowed so different
   trust boundaries coexist on the same host without sharing
   fork pools. PID-by-port keeps the lifecycles isolated.

### Architecture

```
   Any MCP-aware HTTP/SSE client
   (Hermes, Claude Code, Codex, OpenCode, Cline,
    Kilocode, custom script)
        │
        │  GET  /sse?profile=<name>[&tenant=<v>][&env=<key>.<var>=<value>]*
        │       (X-Profile and X-Tenant headers are alternatives to ?)
        │       (Authorization: Bearer *** when bound non-loopback)
        │       (X-Kanban-Workspace forwarded when set by Kanban worker)
        │
        │  POST /messages?session_id=<id>
        │       (endpoint announced by SSE stream; no env override;
        │        profile + tenant are also frozen from the /sse request)
        ▼
┌──────────────────────────────────────────────────────────┐
│  irigate-mcp-proxy                                       │
│  ─ profiles loaded from ~/.irigate/profiles/<name>.yaml │
│  ─ per-SSE-session effective-env merge                  │
│  ─ per-upstream fork pool (TTL-based reaper)            │
│  ─ tenant-scoped profile resolution                     │
│  ─ $HERMES_TENANT + $HERMES_KANBAN_WORKSPACE forwarding  │
│  ─ bearer auth when bound non-loopback                  │
│  ─ security middleware (§Security middleware):          │
│      request: validate → policy → rate-limit → path-jail │
│      response: scrub-secrets → audit-log                │
│  ─ starlette + uvicorn on 127.0.0.1:<port> (or 0.0.0.0) │
│  ─ PID-by-port lifecycle                                │
└──────────────────────────────────────────────────────────┘
        │
        │  middleware runs BETWEEN the agent and the upstream fork.
        │  one stdio / streamable_http client per forked instance
        │  stdio subprocess env: {**os_env, **effective_env,
        │                         HERMES_TENANT (if set on /sse),
        │                         HERMES_KANBAN_WORKSPACE (if set)}
        │  streamable_http outbound headers: {**profile.headers,
        │                                     X-Hermes-Tenant,
        │                                     X-Hermes-Kanban-Workspace}
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

Every upstream in every profile is **connected lazily on first use**
(not at gateway startup). For MCP discovery, `tools/list` is first use:
the gateway initializes each upstream in the selected profile, collects
its tool names, and caches that upstream session/fork until TTL expiry.
For an env-overridden stdio upstream, the first `tools/call` in that
SSE session is first use for that env fingerprint. Each fork has its
own TTL; the background reaper (see §Fork semantics) tears down forks
that have been idle longer than their TTL. Cold-start cost is paid once
per upstream per TTL window, not once per session.

### Routing contract

The gateway exposes:

| Method | Path | Query / Header | Behaviour |
|--------|------|----------------|-----------|
| `GET`  | `/sse` | `?profile=<name>` required; `?tenant=<v>` and `?workspace=<abs-path>` optional; `?env=<key>.<var>=<value>` optional, repeatable | Open SSE stream. Effective env is computed and frozen for the session. Tenant is resolved against the profile's `tenants:` allowlist (empty = wildcard). `X-Tenant:` and `X-Kanban-Workspace:` headers are alternatives to the query parameters. The first SSE event announces `/messages?session_id=<id>` as the POST endpoint. |
| `POST` | `/messages` | `?session_id=<id>` required; `?env=` and `?tenant=` rejected; `X-Profile` / `X-Tenant` / `X-Kanban-Workspace` ignored when `session_id` is present | JSON-RPC request channel for the already-open SSE session. Profile, tenant, and env come from the `SessionState` created by `/sse`, never from the POST request. |
| `GET`  | `/profiles` | `?tenant=<v>` optional | JSON list of profile names + descriptions (no secrets). When `?tenant=` is present, the list is filtered to profiles whose `tenants:` allows the value (or is empty). When the parameter is absent, every profile is listed. |
| `GET`  | `/profiles/<name>` | — | JSON profile dump with env *names* + descriptions only, never values. The `tenants:` allowlist (or absence) is included. |
| `GET`  | `/profiles/<name>/schema` | — | Machine-readable: `<upstream-key>.<VAR-NAME>` pairs the gateway accepts on `?env=`. |
| `GET`  | `/healthz` | — | 200 OK with `{"status":"ok","upstreams":N,"forks":M,"port":<port>}` for liveness probes. `forks` is the sum of live `ForkedInstance` counts across all upstream keys; increments on `tools/call`, decrements when the reaper tears one down. |
| `GET`  | `/` | — | 404 with body `irigate-mcp-proxy. Set X-Profile header or ?profile= query. See /profiles for available profiles.` |

Routing order on `?profile=`:

1. On `GET /sse`, read `?profile=` (query wins).
2. Fall back to `X-Profile` header.
3. If neither is present: 400 with the `GET /profiles` body inline.
4. On `POST /messages`, ignore `?profile=` and `X-Profile`; resolve
   the profile only from `?session_id=<id>`. A missing or unknown
   `session_id` returns HTTP 400.

Tenant filter is applied AFTER profile resolution. Once `profile_name`
is known:

1. Read `?tenant=` (query wins), fall back to `X-Tenant:` header.
2. If both are absent: skip the check entirely. Profile remains
   reachable regardless of any `tenants:` key on it (this preserves
   legacy behaviour for headerless callers — Claude Code, Codex,
   OpenCode, etc.).
3. If a value is present: profile is accepted iff its `tenants:`
   list is empty OR contains the value. Otherwise the gateway returns
   HTTP 403 with the body `{"error":"tenant_not_allowed","tenant":<v>,
   "profiles_for_tenant":<filtered names>}` so the caller can recover
   by sending a different header or asking for the filtered list.

When the resolved profile's `tenants:` is non-empty AND the request
carries an `X-Tenant` (or `?tenant=`) value that is NOT in the list,
the gateway returns HTTP 403. **Headerless callers (no `X-Tenant`,
no `?tenant=`) are always allowed through**, even against profiles
with `tenants:` declared — this preserves the contract that
header-agnostic clients like Claude Code / Codex / OpenCode can
keep using the gateway without modification. Tenant scoping is
opt-in for both sides: the caller opts in by setting the header;
the operator opts in by populating `tenants:`.

#### SSE session registry

`GET /sse` creates a `SessionState` and stores it until the SSE stream
disconnects:

```python
SessionState:
    session_id: str                  # URL-safe random id generated by the gateway
    profile_name: str                # resolved from ?profile= / X-Profile at /sse time
    tenant: str | None               # resolved from ?tenant= / X-Tenant at /sse time, or None
    kanban_workspace: str | None     # resolved from X-Kanban-Workspace at /sse time, or None (always an absolute path or None)
    effective_env: dict[str, dict[str, str]]
    created_at: float                # monotonic time
    last_seen_at: float              # updated on every POST /messages
```

`sessions: dict[str, SessionState]` is the only source of truth for
`POST /messages`. This is not optional: without this registry the
gateway cannot bind a later JSON-RPC request to the profile/env chosen
on the SSE connection. On SSE disconnect, remove the `SessionState`;
forked upstream processes are not killed immediately unless their TTL
expires or the gateway shuts down.

Routing order on `?env=`:

1. Parse each `&env=<key>.<var>=<value>` segment.
2. Validate `<key>` exists in the resolved profile.
3. Validate `<var>` is declared in that upstream's `env:` block.
4. URL-decode the value (percent-encoding + `+` for space).
5. Build a per-session `effective_env[key][var] = value` map.
   The map is frozen at `/sse` connection time and applies for the
   entire SSE session. No fork is spawned yet.
6. On the **first use** of a given upstream, the gateway computes an
   `env_fingerprint` for that upstream by hashing the merged effective
   env. For normal discovery, `tools/list` is first use for upstreams
   with no override. For an env-overridden stdio upstream, the first
   `tools/call` in that SSE session is first use for that specific
   fingerprint. The gateway looks up
   `fork_pool[(upstream_key, env_fingerprint)]`. If no fork exists,
   it spawns a subprocess with the effective env merged into the
   upstream's base env (filtered by `upstreams[i].inherit_os_env:`).
7. Unknown upstream-key or var-name returns 400 with the
   `/profiles/<name>/schema` body inline so the caller can fix it.

### Fork semantics

The "fork" is a stdio MCP subprocess spawned with a specific effective
env. It is **not** a process fork in the OS sense — it is a new
`subprocess.Popen` (via `mcp.client.stdio.stdio_client` →
`StdioServerParameters(command=..., args=..., env=...)`).

```
fork_pool: dict[upstream_key, dict[env_fingerprint, ForkedInstance]]

ForkedInstance:
    env_fingerprint: str          # sha256 of sorted (var, value) pairs
    process: asyncio.subprocess.Process
    session: mcp.ClientSession
    last_used_at: float           # monotonic time of last completed call
    in_flight: int                # number of tool calls executing
    ttl_seconds: int              # from upstream profile entry, default 300

http_session_pools: dict[upstream_key, dict[header_fingerprint, HttpSessionInstance]]

HttpSessionInstance:
    header_fingerprint: str       # sha256 of sorted outbound header pairs
    session: mcp.ClientSession
    last_used_at: float
    in_flight: int
    ttl_seconds: int              # same default/override as stdio upstreams
```

#### TTL-based reaper

Each upstream declares `ttl_seconds` in its profile entry. The
default is 300. The gateway runs a single background asyncio task
(reaper) that wakes every
`min(upstream.ttl_seconds across all upstreams) / 10` seconds
(or every 5 s, whichever is smaller) and reaps any
`ForkedInstance` where:

1. `in_flight == 0` (no calls currently executing on this fork), AND
2. `monotonic_time - last_used_at > ttl_seconds`.

Reaping a stdio fork means: `await session.__aexit__()`, SIGTERM the
subprocess, poll `process.returncode` for up to the grace period
(constant `FORK_REAPER_GRACE_SECONDS = 1.0`, overridable via
`IRIGATE_REAPER_GRACE_SECONDS` env var), then SIGKILL survivors, then
remove the entry from `fork_pool`. Reaping an HTTP session means closing
the `ClientSession` / transport context and removing it from
`http_session_pools`; there is no process signal.

The reaper is a single shared task (one per gateway process, not
one per upstream) so it does not contend with the per-upstream
`asyncio.Lock` during high call volume.

#### Hard cap as backstop

`MAX_FORKED_INSTANCES_PER_UPSTREAM = 16` (hard cap, NOT an LRU
policy). When `len(fork_pool[upstream_key]) >= 16` and a new
`tools/call` would require a 17th fork, the gateway returns
`429 Too Many Forks` with `Retry-After: <ttl_seconds>` and a stderr
log naming the upstream key. This backstop protects against
pathological workloads where unique env_fingerprints arrive faster
than TTL can reap them (a misconfiguration; operators tune the
profile or rate-limit the caller).

The TTL reaper is the primary mechanism; the 16-cap is the
emergency brake. Operators tune either knob per-profile:

```yaml
upstreams:
  - key: DocumentDB
    transport: stdio
    command: npx
    args: ["-y", "awslabs.documentdb-mcp-server@latest"]
    env:
      # VALUES ARE DESCRIPTIONS, NEVER SECRETS OR DEFAULTS.
      # The gateway never reads a literal secret from the profile;
      # operators inject the real value at call time via ?env=.
      DOCUMENTDB_CONNECTION_STRING: "MongoDB connection string for the local DocumentDB instance; supply via ?env=DocumentDB.DOCUMENTDB_CONNECTION_STRING="
    ttl_seconds: 1800      # 30 min — npx spawn is expensive (~2s)
    call_timeout_seconds: 15

  - key: echo              # smoke-test only
    transport: stdio
    command: python3
    args: ["-m", "irigate.mcp_smoke_echo"]
    env:
      TEST_KEY: "Test env var; supply distinct values via ?env=echo.TEST_KEY=value_N to force unique env_fingerprints."
    ttl_seconds: 30        # 30 s — cheap to spawn
    call_timeout_seconds: 10
```

#### Cold-start amortization

The TTL model amortizes cold-start cost across the entire TTL
window. An upstream spawned at `t=0` for one SSE session stays
warm through `t=ttl_seconds`; any subsequent call (from any SSE
session, any agent) within that window reuses the same fork at
zero spawn cost. After `t=ttl_seconds + grace`, the reaper tears
it down and the next call pays the cold-start cost again.

For DocumentDB's `npx` (~2 s cold start) with `ttl_seconds: 1800`
and a typical agent making 1 call per minute, the effective
cold-start penalty is amortized to ~0.001 s/call.

#### HTTP/SSE upstreams

HTTP/SSE upstreams are processless but still pooled: they do not have
a subprocess fork pool, but they DO have a client-session pool keyed by
`(upstream_key, header_fingerprint)`. A header fingerprint is the
sha256 of the effective outbound headers for that HTTP upstream
(`headers:` from the profile plus any `?env=`-derived headers). This
lets two SSE sessions with different `ASTRO_TOKEN` values use separate
HTTP `ClientSession`s instead of racing over one shared session. The
`ttl_seconds` field on an HTTP upstream applies to these pooled HTTP
sessions too: the reaper closes idle HTTP client sessions the same way
it closes idle stdio forks, except there is no subprocess to SIGTERM.

`?env=` overrides on HTTP/streamable_http upstreams are applied as
**outbound HTTP headers** on the pooled HTTP `ClientSession`, not
subprocess env (there is no subprocess).
The header mapping is fixed by this spec (not left to the implementer):

* A var whose name matches `*_TOKEN`, `*_API_KEY`, or `*_SECRET`
  (case-insensitive suffix) is sent as an HTTP Authorization header
  with the Bearer scheme and the supplied value.
  This matches how token-bearing
  upstreams (Astro's `ASTRO_TOKEN`, generic API keys) expect
  credentials.
* Any other declared var is sent as `X-Env-<VAR-NAME>: <value>`.

At most one bearer-mapped var may be supplied for a given HTTP
upstream in one SSE session. If two vars map to `Authorization`, return
HTTP 400 during `/sse` validation with a message naming the conflicting
var names (not their values). If profile `headers:` already contains
`Authorization` and `?env=` supplies a bearer-mapped var, the dynamic
`?env=` value wins for that SSE session; log a DEBUG message naming the
upstream and header key, never the token value.

The effective header set is fixed at `/sse` time and used to choose the
HTTP client-session pool entry. If an upstream requires a different
header name (e.g. `X-Astro-Key`), the operator authors a profile entry
with a pre-populated `headers:` block instead of using `?env=` for that
var — `?env=` is the dynamic path, `headers:` is the static path. The
mapping regex is a constant (`TOKEN_VAR_SUFFIXES = ("_TOKEN",
"_API_KEY", "_SECRET")`); it is not per-profile configurable in Phase 1.

#### Tenant forwarding

The gateway bridges `$HERMES_TENANT` and `$HERMES_KANBAN_WORKSPACE`
(the variables the Kanban dispatcher injects into every spawned
worker) from the inbound HTTP request into the spawned upstream's
environment and outbound headers. This is the path that lets a Kanban
worker's tenant + workspace context reach filesystem- and git-based
MCP servers (code-review-graph, custom git MCPs) without those
servers knowing anything about the Kanban data model.

**Inbound contract (`GET /sse`):**

| Source | Tenant | Workspace |
|--------|--------|-----------|
| Query parameter | `?tenant=<value>` | `?workspace=<abs-path>` (URL-encoded) |
| HTTP header | `X-Tenant: <value>` | `X-Kanban-Workspace: <abs-path>` |

Precedence is **query > header**, matching `?profile=` precedence.
Both are optional. The gateway does NOT auto-derive either from the
request URL or from anything in the agent's process env — the operator
sets them explicitly per request. The Kanban dispatcher does that
itself on the outbound `/sse` request, so this is a zero-touch
integration on the operator side: a Kanban worker running against a
profile that has `tenants: [business-a, business-b]` declared
automatically forwards both vars.

**Workspace path validation.** `X-Kanban-Workspace` MUST be an
absolute path. The gateway rejects any path that does not start with
`/` (Windows drive letters and UNC paths are not accepted in Phase 1 —
the canonical deployment is WSL/POSIX). The check is a literal
`path.startswith("/")` rather than a `pathlib.Path.is_absolute()`
call: `is_absolute()` accepts a few platform-dependent forms (e.g.
drive-rooted Windows paths), and the gateway should refuse them
explicitly rather than letting `subprocess.Popen(cwd=path)` semantics
vary by OS. A non-absolute path returns HTTP 400 with
`{"error":"workspace_path_must_be_absolute","received":<path>}`.

**Outbound contract (per upstream):**

* **stdio upstreams** — when a fork is spawned, the gateway merges
  the following into the subprocess env, in this order (later
  overrides earlier):
  1. Filtered OS env (per `upstreams[i].inherit_os_env:`).
  2. The upstream's declared base `env:` block.
  3. Per-session `?env=` overrides.
  4. `HERMES_TENANT=<session.tenant>` if set.
  5. `HERMES_KANBAN_WORKSPACE=<session.kanban_workspace>` if set.

  The vars are written verbatim with their canonical Hermes names so
  any upstream that explicitly looks for them (Kanban-aware MCP
  servers, third-party MCP servers with Kanban integration) sees the
  same names it would see running under a direct Kanban-spawned
  worker. They are NOT prefixed with `IRIGATE_*`, `X_Env_*`, or
  anything else — `HERMES_*` is the contract from the Kanban docs.

* **streamable_http / sse upstreams** — for every outbound request
  (initialize, `tools/list`, `tools/call`, etc.), the gateway adds:
  * `X-Hermes-Tenant: <value>` if `session.tenant` is set.
  * `X-Hermes-Kanban-Workspace: <value>` if `session.kanban_workspace`
    is set.

  These are sent regardless of profile `headers:`, so an upstream that
  does not implement the Kanban convention simply sees harmless extra
  headers. Both are added to the per-upstream outbound header
  fingerprint so each `(upstream_key, (session, tenant, workspace))`
  tuple gets its own pooled HTTP `ClientSession`. This means: two
  sessions with the same tenant but different workspaces fork
  distinct HTTP clients, exactly the same way distinct `?env=`
  fingerprints do.

  The outbound header names mirror the inbound header names with
  `X-` added (HTTP convention) — the inbound `X-Tenant` is exposed
  as `X-Hermes-Tenant` outbound because HTTP intermediaries should
  not confuse an inbound tenant selector with an outbound data
  attribute. They are not renamed to e.g. `X-Kanban-Tenant` because
  the referenced environment variable is `$HERMES_TENANT` and the
  upstream is more likely to have a tenant concept than to know
  about Kanban specifically.

**Fork-pool key impact.** The `env_fingerprint` for a stdio fork now
hashes the unioned env including `HERMES_TENANT` and
`HERMES_KANBAN_WORKSPACE` when those are set. This means a single
profile with tenant-scoped forks (`tenants: [business-a, business-b]`,
two Kanban sessions both routing through it) gets one fork per
`HERMES_TENANT` value, exactly the right behaviour: the tenant IS the
isolation unit, and a fork straddling two tenants would be a data-
leak vector. The hard cap (`MAX_FORKED_INSTANCES_PER_UPSTREAM = 16`)
still bounds this.

**Why the tenant is folded into `env_fingerprint` and not into the
pool key separately.** Splitting "fork by tenant" from "fork by env"
into two orthogonal keys would let two sessions with different
tenants share a fork whose effective env contains *neither* tenant —
exactly the wrong direction. Treating tenant + workspace as part of
the env dict keeps the fork-pool's invariant ("a fork never serves
two distinct env contexts") uniform with the `?env=` story.

### Performance model

The operator's directive (2026-07-06):

> the architecture should also be high performant so that one
> mcp_server on the gateway does not block queries on other
> mcp_server. the intension is to get the implementation running an
> Amazon Web Services bot also standalon[e]

Per-upstream concurrency invariants:

1. **`asyncio.Lock` per upstream.** All `ClientSession.call_tool`
   invocations against the same upstream serialise behind one lock.
   Different upstreams never block each other.
2. **HTTP/SSE upstreams are stateless; no fork pool.** They share
   one `ClientSession` per upstream with per-call locking (see
   §HTTP/SSE upstreams). The per-upstream lock still applies, so
   concurrent calls to the same HTTP upstream serialise; calls to
   different upstreams do not.
3. **TTL-based fork pool (canonical statement in §Fork semantics).**
   Do NOT restate the model here — the authoritative description is
   in §Fork semantics (reaper cadence, grace period, hard cap,
   cold-start amortization). This bullet exists only to index it
   under "performance invariants": the fork pool is what makes
   "one slow upstream does not block another" true for stdio
   upstreams.
4. **Per-call timeout.** Each upstream's `call_timeout_seconds`
   (declared in the profile, default 30 s) bounds how long a hung
   upstream can block its SSE session. Other SSE sessions on other
   upstreams are unaffected.
5. **starlette async dispatch.** The HTTP/SSE layer is fully async.
   No threadpool dispatching, no synchronous YAML loading on the
   request path.
6. **Profile YAML loaded once at startup.** All `upstreams` blocks
   parsed into memory before the gateway binds the port. Hot reload
   is explicitly a non-goal.

End-to-end expected behaviour (worked example, an agent calling
DocumentDB):

* Agent opens
  `GET /sse?profile=hermes-vc-gateway&env=DocumentDB.DOCUMENTDB_CONNECTION_STRING=***`
* Gateway resolves profile `hermes-vc-gateway`, validates the env
  override against the schema (`DocumentDB` upstream declares
  `DOCUMENTDB_CONNECTION_STRING`), creates a `SessionState`, and
  returns the SSE stream with `/messages?session_id=<id>` as the POST
  endpoint. No DocumentDB subprocess is spawned yet.
* Agent's first `tools/call` against `list_collections` (the
  DocumentDB tool, exposed unprefixed per §Constraints — the agent
  sees it as `mcp__<mcpServers-key>__list_collections`, e.g.
  `mcp__irigate__list_collections`) computes the DocumentDB
  env_fingerprint, spawns/reuses the matching DocumentDB fork, then
  awaits the call behind the DocumentDB `asyncio.Lock`.
* Concurrently, if a different agent calls a code-review-graph
  tool, that call does not block on DocumentDB — different upstream,
  different lock, different fork pool slot.
* The DocumentDB subprocess dies when (a) the agent's SSE session
  ends, (b) `ttl_seconds` (default 300) elapses since the last call
  and the reaper reaps it, or (c) the gateway shuts down.

### Filesystem upstream (compliance-hardened)

The `filesystem` upstream (profile key `fs`) is the eighth entry in
the `hermes-vc-gateway` profile. It is a **compliance-hardened
filesystem MCP server**: a stdio subprocess that exposes a small set
of filesystem tools (`read_file`, `write_file`, `list_directory`,
`search_in_files`, etc.) and enforces three security policies **in
the upstream itself**, not in the gateway. The gateway treats this
upstream like any other stdio upstream (fork pool, TTL reaper,
per-call lock, env forwarding); the security posture is documented
here so the operator knows what to expect and so the verification
checklist can prove the policies hold end-to-end.

The design draws on the security features of `Donnyb369/mcp-spine`
(deny-list filtering, path-jail, structured audit) and the
curated deny-list defaults of `EdibleTuber/mcp-server` (Void editor
filesystem server). The gateway's role is limited to:

1. Mounting the upstream in the profile, with the same per-upstream
   machinery as DocumentDB, code-review-graph, etc.
2. Forwarding `HERMES_TENANT` / `HERMES_KANBAN_WORKSPACE` to the
   upstream subprocess (the upstream uses `$HERMES_KANBAN_WORKSPACE`
   as the default `allowed_root` when set, so Kanban workers get an
   automatic cwd-scoped jail).
3. Documenting the upstream's contract in this section so a future
   implementer (or a future operator reviewing the profile) knows
   what the upstream is supposed to enforce.

**What the gateway does NOT do for this upstream — strictly.**
The §Filesystem upstream's deny-list, path-jail, size
limits, extension allow-list, and structured audit hook
are enforced by the upstream itself. The upstream is
authoritative. The §Security middleware (defense-in-depth)
adds a *second* path-jail and deny-list at the transport
boundary, but it does not duplicate the upstream's
read-only flag, extension allow-list, or size limits —
those are filesystem-specific and belong to the upstream.
The gateway's role is limited to:

1. Mounting the upstream in the profile, with the same per-upstream
   machinery as DocumentDB, code-review-graph, etc.
2. Forwarding `HERMES_TENANT` / `HERMES_KANBAN_WORKSPACE` to the
   upstream subprocess (the upstream uses `$HERMES_KANBAN_WORKSPACE`
   as the default `allowed_root` when set, so Kanban workers get an
   automatic cwd-scoped jail).
3. Documenting the upstream's contract in this section so a future
   implementer (or a future operator reviewing the profile) knows
   what the upstream is supposed to enforce.
4. Applying the §Security middleware (defense-in-depth) layer to
   every `tools/call` and response, including the second path-jail
   and the secret-scrubbing on responses. This is additive to the
   upstream's enforcement, not a replacement.

This is the explicit decision in §Non-goals: the gateway
stays a transport broker; security policies live with the
tool that performs the action. Future revisions may add a
generic upstream-agnostic policy layer (Phase 2+); this
spec deliberately does not.

#### Upstream contract (what the upstream MUST enforce)

A compliant `fs` upstream satisfies the following. None of these
checks is enforced by the gateway; the gateway's only role is to
treat the upstream's responses at face value (a `PermissionError`
from the upstream is a 4xx-equivalent to the agent, not a
gateway-level rejection).

* **Deny-list (default).** The upstream MUST block reads, writes,
  listings, and searches of paths whose basename matches any of
  the following default patterns, regardless of which directory
  the request targets:
  - `.env`, `.env.*`, `.envrc`
  - `*.key`, `*.pem`, `*.p12`, `*.pfx`
  - `id_rsa`, `id_rsa.*`, `id_ed25519`, `id_ed25519.*`
  - `*.gpg` (encrypted or otherwise)
  - Files inside any directory named `.ssh`, `.gnupg`, or `.aws`
  - Files inside any directory named `.git`
  The upstream MUST return a structured error
  (`{blocked: true, rule: "deny_list", pattern: <matched>}`) so a
  caller can tell deny-list rejections apart from other errors.
  Patterns are case-insensitive on case-insensitive filesystems
  (HFS+, APFS, NTFS, Windows shares) and case-sensitive on
  case-sensitive ones (ext4, btrfs, APFS case-sensitive).

* **Deny-list is configurable, not silent.** The upstream MUST
  accept a `blocked_patterns:` block in its own config (or in the
  gateway's `upstreams[i].fs:` block — see §Profile shape) that
  ADDS to the defaults. Removing a default pattern MUST require an
  explicit `allow_override: true` flag plus a per-pattern
  allow-list; the spec REQUIRES a default-deny posture. The
  rationale: a deny-list that's easy to disable is not a
  deny-list.

* **Path-jail with symlink awareness.** The upstream MUST resolve
  every path through `pathlib.Path.resolve()` and verify the
  resolved path is inside `allowed_root` (a directory declared
  in the profile or supplied via `?env=fs.ALLOWED_ROOT=…`). The
  upstream MUST refuse to follow a symlink whose target lies
  outside `allowed_root`, even if the symlink itself is inside
  the jail. This is the same class of bug as CVE-2025-53109
  (EscapeRoute) in the upstream Anthropic filesystem server, so
  the upstream is REQUIRED to test its symlink handling and the
  §Verification step 20 exercises it end-to-end.

* **Size limits.** The upstream MUST refuse to read or write
  files larger than `max_file_size_mb` (default 10 MB). Reads
  above the limit return a structured error, not a truncated
  buffer.

* **Extension allow-list.** The upstream MUST refuse to operate
  on files whose extension is not in its `allowed_extensions:`
  list (default: a curated set of text extensions: `.py`, `.md`,
  `.json`, `.yaml`, `.yml`, `.toml`, `.txt`, `.sh`, `.ts`,
  `.tsx`, `.js`, `.jsx`, `.html`, `.css`, `.sql`, `.cfg`, `.ini`,
  `.xml`). Binary files are out of scope for the upstream in
  Phase 1; operators who need binary support choose a different
  upstream.

* **Structured audit hook.** The upstream MUST log every
  accepted and rejected call to stderr in a JSON-lines format
  the gateway can ingest. The format is:

  ```json
  {"ts": "<ISO-8601 UTC>", "session_id": "<UUID>",
   "tool": "read_file", "path": "<resolved abs path>",
   "outcome": "allowed|denied", "rule": "<deny_list|path_jail|size|extension|null>",
   "tenant": "<value or null>", "workspace": "<value or null>"}
  ```

  The gateway MAY (but does NOT in Phase 1) tee these lines into
  a per-upstream audit file. The format is the contract; the
  storage location is the operator's choice. Phase 2 of irigate
  will likely absorb this into a unified audit log; the
  structured format keeps that path open without locking the
  upstream to a specific writer.

#### What the upstream does NOT do

* **It does not authenticate the caller.** Authentication of
  agents / users is the gateway's job (bearer token when bound
  non-loopback). The upstream trusts the gateway and any
  authenticated caller reaching it.
* **It does not enforce tenant isolation.** A Kanban worker
  with `HERMES_TENANT=biz-a` reaches the same upstream as one
  with `HERMES_TENANT=biz-b`. The upstream MAY log the tenant
  (see audit hook); the gateway's tenant check is at the profile
  level, not at the upstream level. Operators who need
  per-tenant filesystem isolation configure different `fs`
  upstream entries with different `allowed_root` values per
  tenant profile, or rely on the upstream's own per-`fs`-instance
  `allowed_root` to do the scoping.
* **It does not implement rate limiting or backpressure.** That
  is the gateway's per-upstream `call_timeout_seconds` plus the
  `asyncio.Lock` + TTL reaper. The upstream accepts calls as
  fast as the gateway delivers them.
* **It does not perform command execution or shell-out.** The
  upstream is a pure file API; no `bash`, no `subprocess.run`,
  no glob expansion. This is the same constraint Anthropic's
  own filesystem server has, and it is REQUIRED here too.

#### Profile shape

The `hermes-vc-gateway.yaml` profile adds the `fs` upstream as
the eighth entry. The full block:

```yaml
- key: fs
  transport: stdio
  command: python3
  args: ["-m", "irigate.mcp_filesystem"]
  env: {}
  # Upstream-internal config is set in the `fs:` block below. The
  # gateway treats everything under `fs:` as opaque and passes it
  # to the upstream verbatim via $IRIGATE_UPSTREAM_CONFIG (a
  # JSON-encoded string). This keeps the gateway's profile schema
  # upstream-agnostic while still letting the fs upstream receive
  # the config it needs.
  fs:
    allowed_roots:
      - "$HERMES_KANBAN_WORKSPACE"   # Kanban workers' cwd, resolved at fork time
      - "~/.irigate/notes"            # operator-curated notes dir (read-only by default)
    blocked_patterns_extra:
      - "*.local.json"                # operator adds to the default deny list
    max_file_size_mb: 10
    read_only: true                   # read_file + list + search only; no write
  inherit_os_env:
    - PATH
    - HOME
    - LANG
    - LC_ALL
    - TZ
  ttl_seconds: 300
  call_timeout_seconds: 15
```

* `IRIGATE_UPSTREAM_CONFIG` is a documented convention for
  upstream-specific config that the gateway does not interpret.
  The gateway serialises the `fs:` block to JSON, sets the
  env var on the forked subprocess, and the upstream reads it
  at startup. This is the same shape the Anthropic `mcp`
  ecosystem uses for env-based config. Phase 2 may add a
  generic `upstream_config: <json>` field to the gateway's
  upstream schema; until then, `IRIGATE_UPSTREAM_CONFIG` is
  the contract for fs-specific knobs.

* `$HERMES_KANBAN_WORKSPACE` is interpolated by the gateway
  before the config is serialised, so the upstream sees a
  literal absolute path (or the empty string when the env var
  is unset, which the upstream MUST treat as "no per-session
  jail, fall back to operator-configured roots only").
  Interpolation runs at fork-spawn time, not at profile-load
  time, so a session with no `X-Kanban-Workspace` header
  passes an empty `allowed_roots` to the upstream and the
  upstream denies the request rather than silently
  over-permitting.

* `read_only: true` is the recommended default. Operators who
  need a write-capable filesystem upstream add a SECOND `fs`
  entry with a different `key` (e.g. `fs-write`) and a
  smaller `allowed_roots:` list. The gateway's tool-name
  routing (first-upstream-wins) means a `write_file` call
  hits whichever `fs` upstream comes first in the profile;
  the read-only upstream is listed first so read_file wins
  for the read path and the write-capable upstream exposes
  its own write_file for explicit use. This is the
  documented pattern; operators who want a single upstream
  that is read-write drop the `read_only: true` flag.

#### Why some of this stays in the upstream

The §Filesystem upstream is the *authoritative* enforcer for
its own deny-list, path-jail, size limits, extension
allow-list, and read-only flag, because the upstream has the
path context to make those decisions correctly (the upstream
resolves the file before checking the size limit, applies
the extension allow-list to the resolved path, etc.). The
gateway does not have that context and would be guessing
about filesystem semantics.

The §Security middleware (defense-in-depth) section adds
two checks at the *transport* boundary that DO apply to
this upstream in addition to the upstream's own:

* **Path-jail on the request.** The gateway's
  `security.path.allowed_roots` mirror the upstream's
  `fs.allowed_roots`, so the gateway's jail is a
  pre-filter. An upstream that ignored its own jail would
  still be caught by the gateway's. See
  §Security middleware (defense-in-depth) for the
  contract.
* **Secret scrubbing on the response.** A response from
  the upstream that leaks a `-----BEGIN RSA PRIVATE
  KEY-----` (e.g. a debug-mode `read_file` against an
  accidentally-allowed key file) is redacted by the
  gateway before it reaches the agent. The upstream
  does not run this filter because it cannot know
  which strings in the file are sensitive.

The upstream's read-only flag, size limit, and extension
allow-list are filesystem-specific and stay in the
upstream. The gateway does not duplicate them. The split
is: filesystem-mutation-specific enforcement in the
upstream; upstream-agnostic transport-level enforcement
in the gateway middleware. Operators who want a
write-capable filesystem upstream add a SECOND `fs`
entry (e.g. `fs-write`) with a different `key` and a
smaller `allowed_roots:` list, per the §Profile shape
guidance.

A future revision (Phase 2+) may add a thin
gateway-level "audit-log every tool call" hook that is
upstream-agnostic and does not change the deny-list
enforcement. The §Security middleware already emits a
per-call audit entry to stderr (see `audit_all_tool_calls`
in §Security middleware (defense-in-depth) → declarative
security policy); a Phase 2 revision may extend that to
an append-only file with HMAC chaining for SIEM
ingestion. That hook is in the §Future enhancements
list. The Phase 1 spec does not add it.

### Security middleware (defense-in-depth)

The gateway runs an in-process security middleware around every
`tools/call`. The middleware is a direct port of the security
layer in `Donnyb369/mcp-spine` (`spine/security/*.py`, ~550 LOC
across eight modules), relocated to
`~/.irigate/lib/irigate/security/` so the gateway ships its own
copy. The middleware is *defense-in-depth*: the §Filesystem
upstream is still authoritative for its own deny-list, path-jail,
and audit hook, and the middleware is the second line that catches
the same threats (and others) at the transport boundary so a
misbehaving or buggy upstream cannot silently leak.

The middleware has eight modules, each with one job. This section
defines the modules AND the exact order in which they run, because
ordering is a security property (a size check that runs after a
regex scan is a DoS vector; a path-jail that runs before the
deny-list wastes work on already-denied paths).

#### Middleware call pipeline

Every inbound JSON-RPC `tools/call` request and every outbound
`CallToolResult` response passes through the pipeline below. The
pipeline is synchronous within one `tools/call`; the gateway does
not interleave stages across calls. Stages 1–4 run on the REQUEST
before the upstream is contacted; stages 5–7 run on the RESPONSE
before it is forwarded to the agent.

```
                     ┌─────────────────────────────────────┐
  agent POST ──────► │  REQUEST pipeline (pre-upstream)     │
  /messages           │                                       │
                     │  1. validate_message (size+shape)    │
                     │  2. resolve_effective_policy          │
                     │  3. rate_limit.check (global+per-tool)│
                     │  4. path_jail.check_args (deny-list   │
                     │     + jail on path-like arg values)   │
                     │                                       │
                     │  ──► forward to upstream ──►          │
                     │                                       │
                     │  RESPONSE pipeline (post-upstream)   │
                     │                                       │
                     │  5. scrub_call_tool_result (secrets   │
                     │     in TextContent + structuredContent│
                     │     ONLY; never Image/Audio/Blob)     │
                     │  6. audit_log.emit (one JSON line to  │
                     │     stderr; args_hash, never args)    │
                     │  7. (rate_limit.record on success)    │
                     └────────────────┬──────────────────────┘
                                      │
                                      ▼
                              agent SSE stream
```

Stage contract (each stage is a function the implementer MUST
provide; the names are stable so §Verification can reference them):

1. **`validate_message(message: dict) -> None`** (raises
   `ValidationError`). Size + shape check on the inbound
   JSON-RPC envelope. Rejects non-dict, wrong `jsonrpc` version,
   unsafe method/tool names (regex
   `^[a-zA-Z_][a-zA-Z0-9_/]*$` for methods,
   `^[a-zA-Z_][a-zA-Z0-9_\-]*$` for tool names), tool names
   longer than 128 chars, argument dicts with more than 100 keys,
   and raw bodies larger than `policy.max_message_size`. This is
   a port of `spine/security/validation.py:27-66`; the gateway
   runs it once per inbound request, before any other stage.

2. **`resolve_effective_policy(profile, upstream_key, session) ->
   EffectivePolicy`**. Merges the profile-level `security:` block
   with the per-upstream override (see §Per-upstream overrides
   below) and the session's tenant/workspace context. Returns the
   `EffectivePolicy` that stages 3–6 read. This stage never
   touches tool content; it is pure config resolution. An
   upstream with `security.enabled: false` (or a profile with no
   `security:` block) returns an `EffectivePolicy` whose every
   enforcement flag is `False`, so stages 3–6 become no-ops.

3. **`rate_limit.check(effective_policy, upstream_key, tool_name)
   -> None`** (raises `RateLimitedError`). Sliding-window check
   against (a) the global bucket for the profile and (b) the
   `(upstream_key, tool_name)` bucket. On denial, raises
   `RateLimitedError(tool, limit, window_seconds, retry_after)`.
   The gateway translates this exception into the JSON-RPC error
   shape defined in §Rate-limit error contract below — it is NOT
   a generic `CallToolResult.isError=true`, because the upstream
   was never contacted.

4. **`path_jail.check_args(effective_policy, tool_name, arguments)
   -> None`** (raises `PathViolation` or `DenyListViolation`).
   Walks every string value in `arguments` (recursively through
   nested dicts/lists). For each value where `is_pathlike(value)`
   is true, applies the deny-list (§Deny-list matcher) and, if
   the policy declares `security.path.allowed_roots`, the jail
   (§`validate_path`). A value that fails either check aborts the
   whole call with the violating rule named in the exception.
   Non-path-like values are skipped — the jail never inspects a
   regex argument or a free-text prompt.

5. **`scrub_call_tool_result(result: CallToolResult,
   effective_policy) -> CallToolResult`**. Returns a NEW
   `CallToolResult` with secrets redacted from the content items
   the agent will actually read. See §Response scrubbing contract
   for the exact walk — this is the stage where the base64-regex
   landmine lives, so the contract is precise about which content
   types are scanned.

6. **`audit_log.emit(session, upstream_key, tool_name, arguments,
   outcome, rule, effective_policy) -> None`**. Writes one
   JSON-lines record to stderr. The record carries an `args_hash`
   (SHA-256 of the canonical-JSON arguments), NEVER the argument
   values themselves. See §Audit record contract.

7. **`rate_limit.record(effective_policy, upstream_key,
   tool_name) -> None`**. On a successful (non-rate-limited,
   non-denied) call, records the timestamp in both the global and
   per-tool buckets so the next call's `check` sees it. This is a
   separate stage from `check` (stage 3) because a call that is
   denied at stage 3 or 4 must NOT consume a rate-limit token —
   otherwise a flood of denied requests would lock out legitimate
   traffic.

**Short-circuit semantics.** Stages 1–4 are fail-closed: the
first stage that raises aborts the call and skips the remaining
request-pipeline stages, skips the upstream contact, and jumps
straight to stage 6 (audit) with `outcome` set to the failing
rule. Stages 5–7 run only on the success path (upstream returned
a result). An upstream-raised JSON-RPC error (the upstream's own
`code: -32603`, etc.) still runs stages 5 and 6 on the error
payload, because upstream error messages are a known secret-leak
vector — an upstream that echoes a connection string in an error
is caught by stage 5.

**Concurrency.** The pipeline runs inside the per-upstream
`asyncio.Lock` the gateway already holds around
`ClientSession.call_tool` (§Reverse-proxy core). The middleware
does not add its own locking. The `RateLimiter`'s in-memory
buckets are single-threaded under the asyncio loop, so no
additional synchronization is needed.

#### Module: `security/validation.py` — request validation

Port of `spine/security/validation.py:1-66`. Implements
`validate_message` (stage 1) and `validate_message_size`.
Constants:

```python
MAX_MESSAGE_SIZE = 10 * 1024 * 1024      # 10 MB; overridable via policy.max_message_size
MAX_SCHEMA_DEPTH = 20                    # recursion guard for nested arguments
MAX_TOOL_NAME_LENGTH = 128
MAX_ARGUMENT_KEYS = 100
_SAFE_METHOD_PATTERN  = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_/]*$")
_SAFE_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\-]*$")
```

A request failing stage 1 returns a JSON-RPC error with
`code = INVALID_REQUEST (-32600)` for shape/version failures,
or `code = INVALID_PARAMS (-32602)` for tool-name / argument
failures. These are standard JSON-RPC codes (see §Error code
allocations); the message names the failed check without
echoing the offending value.

#### Module: `security/rate_limit.py` — sliding-window limiter

Port of `spine/security/rate_limit.py:1-64`. Implements
`RateLimiter` with `RateLimitBucket` per key. The gateway holds
ONE `RateLimiter` instance per process (not per profile, not per
session) so a caller cannot dodge the global bucket by opening
many SSE sessions. Keys are `(profile_name, upstream_key,
tool_name)` tuples for the per-tool bucket and `(profile_name,)`
for the global bucket.

Defaults (from `EffectivePolicy`, overridable per profile and
per upstream):

* `global_rate_limit: 60` — calls per 60 s across all upstreams
  in the profile.
* `per_tool_rate_limit: 30` — calls per 60 s per
  `(upstream_key, tool_name)`.

The window length is fixed at 60.0 s; Phase 1 does not expose a
configurable window (spine's `default_window` is left at its
60 s default). Per-tool overrides use glob patterns against the
tool name (e.g. `file_*: 10`); the matcher is `fnmatch.fnmatch`
(Phase 1 — patterns are operator-authored, not adversarial).

##### Rate-limit error contract

A rate-limit denial is NOT a normal tool result. The upstream
was never contacted, so returning `CallToolResult(isError=True,
...)` would be a lie (it implies the upstream ran and failed).
Instead the gateway returns a JSON-RPC error:

```json
{"jsonrpc": "2.0",
 "error": {"code": -32029,
           "message": "rate_limited",
           "data": {"rule": "rate_limit",
                    "scope": "per_tool|global",
                    "tool": "<name or '*' for global>",
                    "limit": <int>,
                    "window_seconds": 60,
                    "retry_after_seconds": <int estimate>}},
 "id": <request id>}
```

**Error code allocation.** The MCP Python SDK reserves
`[-32000, -32099]` for MCP/implementation-defined errors (see
`mcp/types.py`: `CONNECTION_CLOSED = -32000`,
`URL_ELICITATION_REQUIRED = -32042`). `-32029` is in that band
and is not claimed by the pinned `mcp == 1.27.1` runtime. The
implementer MUST verify at build time that `-32029` is still
unclaimed by grepping `mcp/types.py` for the literal; if a
future SDK release claims it, the gateway bumps to the next
free code in `[-32050, -32099]` and updates this section.

`retry_after_seconds` is computed as
`ceil(window_seconds - (now - oldest_timestamp_in_bucket))`,
clamped to `[1, window_seconds]`. It is an estimate, not a
promise — concurrent calls from other sessions can extend the
actual wait.

#### Module: `security/paths.py` — path jail + deny-list

Ports `spine/security/paths.py:1-54` (the jail) AND absorbs the
deny-list logic from `spine/security/policy.py:37-59`
(`PathPolicy.is_path_allowed`). The two checks are fused because
they share a code path: both need to resolve the candidate path,
and CVE-2025-53109 (EscapeRoute) is precisely a bug where the
deny-list was checked against an un-resolved path while the jail
checked the resolved one. Fusing them removes that class of bug.

##### `is_pathlike(value) -> bool`

The predicate that decides whether a string argument value is
treated as a path by stage 4. Defined exactly (no "heuristic"
language — the implementer copies this):

```python
def is_pathlike(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    # Tilde-expanded home paths are paths.
    if value.startswith("~"):
        return True
    # POSIX absolute paths.
    if value.startswith("/"):
        return True
    # Windows drive-letter absolutes (C:\, D:/) — jail rejects
    # these anyway because the deployment is WSL/POSIX, but we
    # classify them so a misconfigured profile fails closed
    # instead of silently passing a Windows path through.
    if len(value) >= 3 and value[1:3] == ":\\" and value[0].isalpha():
        return True
    # Relative paths with a separator AND a pathy extension or
    # a known path prefix. Bare "foo/bar" is ambiguous (could be
    # a URL path, a key, a branch); require a `.` in the final
    # segment OR a leading `./` OR a leading `../` to count.
    if value.startswith(("./", "../")):
        return True
    last = value.rsplit("/", 1)[-1]
    if "/" in value and "." in last:
        return True
    return False
```

The predicate is deliberately NARROW. Stage 4 skips any value
for which `is_pathlike` returns `False`, so a tool that takes a
regex (`^/etc/.*$`) or a URL path (`/v1/users`) as an argument
is not mistakenly jailed. The trade-off is that a bare relative
path like `secrets.yaml` (no `./` prefix, no `/` separator) is
NOT scanned by the gateway — but the §Filesystem upstream's OWN
jail catches it, because the upstream resolves the path against
its `allowed_root` before opening the file. The gateway's jail
is defense-in-depth, not the primary jail.

##### Deny-list matcher

The deny-list is matched against the RESOLVED path's string
form, not the raw argument. Resolution happens first (next
subsection). Matching uses Python's `fnmatch.translate` converted
to a regex, with ONE deviation from `fnmatch`: `**` is mapped to
`.*` (matches across `/`), while a single `*` is mapped to
`[^/]*` (matches within a path segment). This is the
split/escape/rebuild approach: naive `fnmatch` treats `**` the
same as `*`, which silently weakens patterns like `**/.env` to
`*/.env` — a real bug class the implementer MUST avoid.

```python
def glob_to_regex(pattern: str) -> re.Pattern:
    # Split on runs of '*'; map '**' -> '.*', '*' -> '[^/]*';
    # re.escape() literal segments; anchor at both ends.
    ...
```

Default deny-list patterns (from `spine/security/policy.py:40-51`,
case-normalised on case-insensitive filesystems):

```
**/.env
**/.env.*
**/.envrc
**/secrets.*
**/*.pem
**/*.key
**/*.p12
**/*.pfx
**/id_rsa
**/id_rsa.*
**/id_ed25519
**/id_ed25519.*
**/*.gpg
**/.ssh/**
**/.gnupg/**
**/.aws/**
**/.git/**
```

The profile's `security.path.denied_patterns_extra` ADDS to this
list. Removing a default pattern requires
`security.path.allow_override: ["**/*.pem", ...]` — an explicit
per-pattern opt-out, not a global switch. A deny-list that is
easy to disable is not a deny-list.

##### `validate_path(requested_path, allowed_roots) -> Path`

Port of `spine/security/paths.py:17-45`. Algorithm (the
implementer MUST follow this order — reordering reintroduces
CVE-2025-53109):

1. Reject any `requested_path` containing a NUL byte
   (`"\x00" in requested_path` → `PathViolation`). NUL bytes
   truncate C-string APIs and are never legitimate in a path.
2. `resolved = pathlib.Path(requested_path).resolve()`.
   `resolve()` follows symlinks AND normalises `..`, so the
   resolved path is the canonical on-disk target.
3. For each `root` in `allowed_roots`:
   `root_resolved = pathlib.Path(root).resolve()`. Roots are
   resolved at policy-load time and cached, so this is a single
   comparison per call.
4. If `resolved == root_resolved` OR `resolved.is_relative_to
   (root_resolved)` is true, the path is inside the jail →
   return `resolved` (the caller uses the resolved form).
5. If no root contains the path → raise `PathViolation` naming
   the resolved path and the configured roots (the roots list
   is not secret).

The deny-list (previous subsection) is checked AGAINST the
resolved path AFTER the jail check passes. Order matters: a
path that escapes the jail is rejected before we waste a
deny-list scan on it, and the deny-list sees the canonical
symlink-resolved form so an attacker cannot dodge `**/.env` by
symlinking `.env` to `config`.

##### Allowed-roots interpolation

`security.path.allowed_roots` entries may contain
`${VAR_NAME}` placeholders (notably `${HERMES_KANBAN_WORKSPACE}`).
Resolution uses `security/env.py:resolve_env_vars` (fail-closed:
an unset var raises `ValueError` at policy-load time, never
silently substitutes empty). The gateway resolves roots ONCE at
`/sse` session creation (when `SessionState` is built), NOT at
every `tools/call` — so a session's jail is frozen for its
lifetime, matching the frozen-effective-env contract in
§SSE session registry.

#### Module: `security/secrets.py` — response scrubbing

Port of `spine/security/secrets.py:1-34`. The regex set is
identical to spine's `_SECRET_PATTERNS` with two changes
documented below. Stage 5 calls `scrub_call_tool_result`, which
is the function this section defines precisely — because the
naive "run every regex over the whole response" approach
DESTROYS image and audio content (see landmine below).

##### Pattern set and the base64 landmine

The seven patterns from `spine/security/secrets.py:12-20`:

| # | Name | Regex | Notes |
|---|------|-------|-------|
| 1 | AWS access key | `AKIA[0-9A-Z]{16}` | low false-positive rate |
| 2 | GitHub token | `gh[pousr]_[A-Za-z0-9_]{36,}\|github_pat_[A-Za-z0-9_]{20,}` | low FP |
| 3 | Generic API key | `(?i)(api[_-]?key\|token\|secret\|password)\s*[:=]\s*\S+` | **HIGH FP** — see below |
| 4 | Bearer token | `Bearer\s+[A-Za-z0-9\-._~+/]+=*` | low FP |
| 5 | PEM private key | `-----BEGIN\s+(RSA\|EC\|DSA )?PRIVATE KEY-----` | low FP |
| 6 | Base64 blob | `(?<![A-Za-z0-9])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9])` | **DESTROYS base64 content** — see below |
| 7 | Connection string | `(?i)(postgres\|mysql\|mongodb\|redis)://\S+:\S+@` | low FP |

**Landmine #1 — pattern 6 destroys binary content.** MCP
`ImageContent.data` and `AudioContent.data` are base64 strings
(verified against `mcp == 1.27.1`: both fields are typed `str`
and documented as base64-encoded). Pattern 6 would redact EVERY
image/audio response to `[REDACTED]`, bricking screenshot tools,
vision pipelines, and any upstream that returns images. The
fix is structural, not regex tuning: `scrub_call_tool_result`
(next subsection) runs the regex set ONLY against text-typed
content, never against `ImageContent` / `AudioContent` /
`BlobResourceContents`. Pattern 6 stays in the set because it
catches base64-encoded secrets in text content, but its
application is scoped.

**Landmine #2 — pattern 3 redacts most config files.** The
generic `token=…` / `password=…` / `secret=…` regex matches
nearly every line of a typical config file, every `.env`-style
assignment, and many test fixtures. This is correct behaviour
for a secret-scrubber, but it means the default
`scrub_secrets_in_responses: true` will materially alter
responses from tools that return config-shaped text (the
§Filesystem upstream's `read_file` on a `.ini`, a CI workflow,
a `docker-compose.yml`). The spec accepts this — secret
scrubbing is supposed to err on the side of redaction — but
documents it loudly so operators are not surprised. Per-upstream
opt-out is `security.scrub_secrets: false` (see §Per-upstream
overrides).

##### `scrub_call_tool_result(result, effective_policy) -> CallToolResult`

This is the function stage 5 calls. It returns a NEW
`CallToolResult` (it does not mutate the upstream's result in
place, so the original is available for the audit log if
`scrub_secrets_in_logs: false`). The walk is type-aware:

```python
def scrub_call_tool_result(result, policy):
    if not policy.scrub_secrets_in_responses:
        return result
    new_content = []
    for item in result.content:
        if isinstance(item, TextContent):
            scrubbed = scrub_secrets(item.text)
            if scrubbed != item.text:
                _log_scrub(policy, item.type, match_classes=_detect(item.text))
            new_content.append(TextContent(type="text", text=scrubbed,
                                           annotations=item.annotations))
        elif isinstance(item, (ImageContent, AudioContent)):
            # NEVER scrub binary base64 — landmine #1.
            new_content.append(item)
        elif isinstance(item, EmbeddedResource):
            # Scrub only if the embedded resource is text-typed.
            res = item.resource
            if hasattr(res, "text") and isinstance(res.text, str):
                res = res.model_copy(update={"text": scrub_secrets(res.text)})
            new_content.append(item.model_copy(update={"resource": res}))
        elif isinstance(item, ResourceLink):
            new_content.append(item)   # link, not content
        else:
            new_content.append(item)   # forward-compat: unknown types pass through
    # structuredContent is a dict[str, Any]; scrub its string values.
    new_struct = None
    if result.structuredContent:
        new_struct = _scrub_mapping(result.structuredContent)
    return result.model_copy(update={"content": new_content,
                                     "structuredContent": new_struct})
```

`_scrub_mapping` recurses into nested dicts/lists and applies
`scrub_secrets` to every `str` value, with a recursion cap of
`MAX_SCHEMA_DEPTH = 20` (from `validation.py`) to bound cost on
adversarial payloads. Non-`str` leaf values (ints, bools, None)
pass through untouched.

`_log_scrub` writes a `secret_scrubbed` audit entry naming the
match CLASS (`"AWS Key"`, `"GitHub Token"`, …) and the content
item type, NEVER the matched value. This is how an operator
diagnoses a false positive (§Failure modes): the log shows
`secret_scrubbed class=Base64 Long Secret item=text_content`
without revealing what was redacted.

##### Scrubbing order vs. audit logging

Scrubbing (stage 5) runs BEFORE audit logging (stage 6). This
means the audit log's `args_hash` is computed from the original
arguments (not redacted — arguments are hashed, not stored, so
there is nothing to redact), and the audit record does NOT
carry the response body at all. The response body the agent
receives is the scrubbed one. There is no path by which the
original secret reaches either the agent or the stderr log
when `scrub_secrets_in_logs: true` (the default).

When `scrub_secrets_in_logs: false`, the gateway's stderr log
may contain upstream error messages that include secrets (e.g.
a connection-string echo). This is an operator-acknowledged
trade-off for debugging fidelity; the default is `true`.

#### Module: `security/policy.py` — declarative policy + overrides

Port of `spine/security/policy.py:1-176` (`SecurityPolicy`,
`ToolPolicy`, `PathPolicy`, `NetworkPolicy`, `load_security_policy`).
The gateway loads one `SecurityPolicy` per profile at startup
from the profile's `security:` block. At `/sse` time,
`resolve_effective_policy` (pipeline stage 2) merges it with the
target upstream's override block and the session context.

##### `EffectivePolicy` (the runtime shape stages 3–6 consume)

```python
@dataclass
class EffectivePolicy:
    enabled: bool                       # master switch; False => stages 3-6 are no-ops
    scrub_secrets_in_responses: bool
    scrub_secrets_in_logs: bool
    audit_all_tool_calls: bool
    max_message_size: int               # bytes; stage 1 ceiling
    # rate limiting
    rate_limit_enabled: bool
    global_rate_limit: int              # calls per 60s
    per_tool_rate_limit: int            # calls per 60s per (upstream, tool)
    rate_limit_overrides: dict[str, int]  # glob -> calls per 60s
    # path jail + deny-list
    path_jail_enabled: bool
    allowed_roots: list[Path]           # resolved (env-vars interpolated) at session creation
    denied_patterns: list[str]          # defaults + denied_patterns_extra - allow_override
    allow_override: list[str]           # patterns explicitly removed from defaults
```

Defaults (used when a profile omits `security:` entirely OR an
upstream omits a field the profile sets):

| Field | Default |
|-------|---------|
| `enabled` | `True` (profile-level); inherits from profile at upstream level |
| `scrub_secrets_in_responses` | `True` |
| `scrub_secrets_in_logs` | `True` |
| `audit_all_tool_calls` | `True` |
| `max_message_size` | `10485760` (10 MB) |
| `rate_limit_enabled` | `True` |
| `global_rate_limit` | `60` |
| `per_tool_rate_limit` | `30` |
| `rate_limit_overrides` | `{}` |
| `path_jail_enabled` | `True` |
| `allowed_roots` | `[]` (empty = no jail; the fs upstream's own jail still applies) |
| `denied_patterns` | the 18 default patterns from §Deny-list matcher |
| `allow_override` | `[]` |

##### Per-upstream override precedence

A profile declares a top-level `security:` block. An upstream
entry MAY declare its own `security:` block that overrides any
field. Precedence (highest wins):

1. Upstream-level `security.<field>` (if present).
2. Profile-level `security.<field>` (if present).
3. The default table above.

`enabled` is special: a profile-level `security.enabled: false`
disables the middleware for EVERY upstream in the profile,
ignoring any upstream-level `enabled: true`. This is so an
operator can kill the middleware globally with one flag without
auditing every upstream entry. An upstream-level
`security.enabled: false` disables the middleware for that
upstream only. See §Profile shape for the YAML.

##### Audit record contract

Stage 6 writes one JSON-lines record per `tools/call` to stderr.
The record is the gateway-wide audit trail (the §Filesystem
upstream ALSO writes its own per-call records from inside the
subprocess; both formats coexist and a Phase 2 unified log
ingests both). Record shape:

```json
{"ts": "2026-07-08T12:34:56.789Z",
 "session_id": "<SSE session UUID>",
 "upstream": "<upstream-key>",
 "tool": "<tool name>",
 "args_hash": "<16-char sha256 prefix of canonical-JSON arguments>",
 "outcome": "allowed|denied|rate_limited|error",
 "rule": "deny_list|path_jail|size|extension|rate_limit|validation|null",
 "rule_detail": "<human-readable; e.g. 'pattern **/.env matched'>",
 "tenant": "<X-Tenant value or null>",
 "workspace": "<X-Kanban-Workspace value or null>",
 "duration_ms": <int>}
```

`args_hash` is computed by `integrity.canonical_args_hash`:

```python
def canonical_args_hash(arguments: object) -> str:
    canonical = json.dumps(arguments, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

`default=str` coerces non-JSON-serialisable values (Path,
datetime, custom objects an upstream might pass through) to
their `str()` form so the hash never fails. The hash is a
16-char prefix (64 bits) — enough for correlation, short
enough that the log stays greppable. The arguments themselves
are NEVER written; `args_hash` is a correlation handle, not a
payload.

`outcome` values:
* `allowed` — stages 1–4 passed, upstream returned success.
* `denied` — stage 1 or 4 rejected the call (validation, path
  jail, deny-list). `rule` names which.
* `rate_limited` — stage 3 rejected the call.
* `error` — stages 1–4 passed but the upstream returned a
  JSON-RPC error. `rule` is `null`; `rule_detail` carries the
  upstream's error code/message (scrubbed if
  `scrub_secrets_in_logs: true`).

#### Module: `security/commands.py` — spawn-command guard

Port of `spine/security/commands.py:1-73`. Runs ONCE per
upstream at profile-load time (not per call), validating the
`command` + `args` of every stdio upstream against an
allowlist. The gateway uses `create_subprocess_exec` (not
`shell=True`), so shell metacharacters are not interpreted —
but the guard still blocks them so a misconfigured profile
fails loudly instead of relying on the exec-vs-shell
distinction. Default allowlist:

```python
{"python", "python3", "node", "npx", "uvx", "deno"}
```

An upstream whose command basename (stripped of path + suffix
via `PureWindowsPath(command).stem` for cross-platform safety)
is not in the allowlist fails profile load with a clear error.
Operators extend the list via
`security.allowed_commands: [...]` at the profile level. This
module is the reason the shipped `hermes-vc-gateway.yaml`
entries all use `python3` / `npx` / `uvx` — anything else
would not load.

#### Module: `security/env.py` — fail-closed `${VAR}` resolution

Port of `spine/security/env.py:1-39`. `resolve_env_vars(value)`
substitutes `${VAR_NAME}` patterns, raising `ValueError` for
any unset variable instead of silently substituting empty
string. Used by:
* `security.path.allowed_roots` interpolation (§Allowed-roots
  interpolation).
* The `fs.allowed_roots` interpolation in the §Filesystem
  upstream (the gateway's existing fork-spawn-time
  interpolation is reimplemented in terms of this module so
  both code paths share one resolver).

`safe_env_dict(env_config)` applies `resolve_env_vars` to every
value in a server's `env:` block. The gateway calls this when
building `StdioServerParameters.env` so a profile typo like
`${DOCUMENTDB_CONNETION_STRING}` (missing `C`) fails at fork
time with a clear error instead of spawning an upstream with
an empty credential.

#### Module: `security/integrity.py` — hashing helpers

Port of `spine/security/integrity.py:1-46`. Three functions:
* `hash_content(content: bytes) -> str` — full SHA-256, hex.
  Used by the Phase 2 state-guard (NOT in Phase 1; documented
  here so the module is not dead code).
* `hash_tool_schema(schema: dict) -> str` — 16-char SHA-256 of
  canonical JSON for change detection. Used by the gateway's
  tool-list cache key (so a tools/list whose schema changed
  is treated as a cache miss).
* `audit_fingerprint(event_type, tool_name, timestamp,
  payload_hash, secret_key=None) -> str` — HMAC-SHA256 (or
  plain SHA-256 without a key) for tamper-evident audit. Phase
  1 calls it WITHOUT a `secret_key` (tamper-detectable, not
  tamper-proof); Phase 2 wires `IRIGATE_AUDIT_HMAC_KEY` to
  upgrade to tamper-proof.

#### Why this is defense-in-depth, not replacement

The middleware is a transport-level second line. It does not
replace the §Filesystem upstream's deny-list because:

* The upstream's deny-list operates on paths inside the
  upstream's own `allowed_roots` (the upstream's own jail),
  with full filesystem context (it can `stat` the resolved
  path). The gateway's path-jail operates on the argument
  string BEFORE it reaches the upstream, so an
  attacker-controlled upstream that ignored its own deny-list
  would still be caught by the gateway's.
* The upstream's structured audit hook writes per-upstream
  records from inside the subprocess; the gateway's audit
  trail writes per-call records from the transport layer.
  Both formats coexist; the Phase 2 unified log ingests both.
* The upstream's read-only flag and extension allow-list are
  filesystem-specific; the gateway's path-jail is the
  equivalent for any upstream that takes path-like arguments.

The middleware is a no-op (zero work, zero overhead) for any
upstream on a profile whose `security.enabled` is `False` OR
that has no `security:` block at profile level AND the default
profile-level switch is off. The shipped
`hermes-vc-gateway.yaml` declares a top-level `security:`
block with the defaults above; the shipped `smoke-test.yaml`
does not, so the middleware is inert for the smoke-test
profile unless a verification step explicitly opts in via a
per-fixture profile.

#### Failure modes and operator responses

| Symptom | Likely cause | Operator fix |
|---------|--------------|--------------|
| Agent sees `[REDACTED]` in a text response where no secret is expected | Pattern 3 (generic `key=`) or 6 (base64 blob) false positive on legitimate text | Set `security.scrub_secrets: false` on the affected upstream; check the `secret_scrubbed` audit log entry for the match class to confirm it is a FP before disabling |
| Agent gets `rate_limited` (`-32029`) mid-task | Bursty loop exceeded `per_tool_rate_limit` (30/min default) | Raise the limit via `security.rate_limit_overrides: {"<tool_glob>": <n>}` on the upstream, or `security.rate_limit_enabled: false` to disable |
| Tool call returns `path_jail` denial on a non-path argument | `is_pathlike` classified a regex/URL/path-shaped string as a path | Set `security.path_jail_enabled: false` on the upstream (narrowest), or narrow the profile's `allowed_roots` |
| Image/audio tool response arrives intact (not redacted) | Expected behaviour — stage 5 skips `ImageContent`/`AudioContent` by design (landmine #1) | None — this is correct |
| Profile fails to load with "command not in allowed list" | `security/commands.py` blocked an unrecognised binary | Add the basename to `security.allowed_commands` at the profile level |
| Profile fails to load with `${VAR} is not set` | `security/env.py` fail-closed on an unset env-var reference | Set the env var, or remove the `${VAR}` reference from the profile |
| Debugging needs the original (un-redacted) response in logs | `scrub_secrets_in_logs: true` (default) hides secret values in stderr | Set `security.scrub_secrets_in_logs: false` on the upstream; accept that secrets may appear in the log file |

#### Error code allocations (summary)

The gateway uses these JSON-RPC error codes. All are in the
MCP-reserved `[-32000, -32099]` band or the standard JSON-RPC
`[-32700, -32000]` band; none collide with the pinned SDK's
claimed codes (`-32000`, `-32042`, `-32600..-32603`, `-32700`).

| Code | Meaning | Raised by |
|------|---------|-----------|
| `-32700` | Parse error (standard) | JSON parse failure |
| `-32600` | Invalid request (standard) | `validate_message` shape/version |
| `-32602` | Invalid params (standard) | `validate_message` tool-name/arg-count |
| `-32603` | Internal error (standard) | gateway bug |
| `-32029` | `rate_limited` (gateway-defined) | `rate_limit.check` (stage 3) |
| `-32030` | `path_jail_violation` (gateway-defined) | `path_jail.check_args` (stage 4) |
| `-32031` | `deny_list_violation` (gateway-defined) | `path_jail.check_args` (stage 4) |
| `-32032` | `validation_error` (gateway-defined) | `validate_message` overflow (when `-32602` is too generic) |

`-32030`/`-32031`/`-32032` are allocated here and MUST be
checked against `mcp/types.py` at build time the same way
`-32029` is.

## Implementation

### Files to create

```
~/.irigate/
  bin/
    irigate_mcp_proxy.py           # the gateway (~300-400 lines)
  lib/irigate/
    __init__.py                    # namespace package marker
    mcp_smoke_echo.py              # the smoke-test echo upstream (see below)
    mcp_filesystem.py              # the compliance-hardened filesystem upstream (see §Filesystem upstream)
    mcp_mw_path_fixture.py         # one-screen upstream exposing read_path(path: str) -> str for §Verification step 22 (security middleware path-jail). The implementer lands this alongside mcp_smoke_echo.py.
    mcp_mw_secrets_fixture.py      # one-screen upstream returning a string with embedded AWS / GitHub / connection-string secrets for §Verification step 23 (security middleware secret scrubbing). The implementer lands this alongside mcp_smoke_echo.py.
    security/                      # the security middleware (see §Security middleware (defense-in-depth))
      __init__.py
      validation.py                # request validation: size/shape/method/tool-name/arg-count (port of spine/security/validation.py)
      rate_limit.py                # sliding-window rate limiting, global + per-tool (port of spine/security/rate_limit.py)
      paths.py                     # path jail with symlink awareness + deny-list matcher (port of spine/security/paths.py + policy.py PathPolicy)
      secrets.py                   # regex-based secret scrubbing + scrub_call_tool_result walker (port of spine/security/secrets.py)
      policy.py                    # EffectivePolicy dataclass + resolve_effective_policy + per-upstream merge (port of spine/security/policy.py)
      commands.py                  # spawn-command allowlist guard, runs at profile-load (port of spine/security/commands.py)
      env.py                       # fail-closed ${VAR} resolution (port of spine/security/env.py)
      integrity.py                 # SHA-256 / HMAC hashing helpers for audit + schema cache (port of spine/security/integrity.py)
  profiles/
    hermes-vc-gateway.yaml         # heavy shared profile (8 upstreams; see §Filesystem upstream)
    smoke-test.yaml                # verification fixture (1 upstream)
  logs/
    mcp-gateway-<port>.pid
    mcp-gateway-<port>.log
```

The two profile YAML files are operator-authored. Reference
copies are committed to this repo at
`profiles/<name>.yaml`; the operator copies them
to `~/.irigate/profiles/` and edits per-environment (URLs, paths,
secret names). The gateway ships `irigate_mcp_proxy.py` and the
smoke-test echo upstream at `~/.irigate/lib/irigate/mcp_smoke_echo.py`.

#### `mcp_smoke_echo.py` — smoke-test upstream surface

The smoke-test profile's only upstream is `python3 -m irigate.mcp_smoke_echo`.
It is a minimal stdio MCP server with no external backend, no network, no
credentials. It MUST expose exactly one tool so that verification steps
that issue `tools/call` (12 and 13) have something to invoke:

* **`echo(message: str) -> str`** — the only entry returned by
  `tools/list`; returns its input unchanged, used to force a
  `tools/call` round-trip through the gateway (and thus a fork).
  `resources/list` and `prompts/list` return empty sets.
* **`whoami_env() -> dict`** — returns a JSON object with the values
  of `HERMES_TENANT`, `HERMES_KANBAN_WORKSPACE`, and `TEST_KEY` as the
  subprocess sees them (each value a string, or `null` if unset).
  Used by §Verification step 17 to confirm the gateway's tenant /
  workspace forwarding contract landed in the forked subprocess
  unmodified. Implementers should redact this tool from any production
  upstream; it exists solely for the smoke-test fixture.
* It reads `TEST_KEY` from its environment only so that distinct `?env=`
  values produce distinct `env_fingerprint`s; it does NOT echo the value
  back to the client (that would leak the override). `TEST_KEY` influences
  fork identity, not tool output. `whoami_env` is the one exception:
  verification step 17 is precisely the test that reads these vars back,
  and that test runs only against the smoke-test fixture, never against
  a production profile.

The module is implemented against the same pinned `mcp` SDK as the gateway
(`mcp.server.Server` + `@server.list_tools()` / `@server.call_tool()`
decorators, or `mcp.server.fastmcp.FastMCP` — whichever the gateway itself
uses, so the two stay in lockstep). It must be importable as
`irigate.mcp_smoke_echo`, i.e. `~/.irigate/lib` is on `PYTHONPATH` when the
gateway spawns it (the gateway sets this when launching stdio upstreams
whose `command` is `python3 -m irigate.*`).

#### `mcp_mw_path_fixture.py` — security-middleware path-jail fixture

A one-screen stdio MCP server (same `mcp.server.Server` shape as
`mcp_smoke_echo.py`) used exclusively by §Verification step 22. It
exposes exactly one tool so the gateway's path-jail has a
path-shaped argument to inspect:

* **`read_path(path: str) -> str`** — reads the file at `path`
  and returns its decoded text content as a `TextContent` item.
  The fixture itself performs NO path validation — it opens the
  file with `pathlib.Path(path).read_text(encoding="utf-8")` and
  returns the content. If the gateway's path-jail (stage 4) is
  working, the fixture is never reached for a denied path; if
  the jail is bypassed or misconfigured, the fixture reads
  whatever the OS allows, which is what step 22 detects (a
  denied path returning content = jail failure).

Tool-list shape (`tools/list` returns exactly this one entry):

```json
{"name": "read_path",
 "description": "Read a file and return its text. For security-middleware path-jail verification only.",
 "inputSchema": {"type": "object",
                 "properties": {"path": {"type": "string"}},
                 "required": ["path"]}}
```

Call result shape (success):

```json
{"content": [{"type": "text", "text": "<file contents>"}],
 "isError": false}
```

The fixture MUST NOT implement its own deny-list or path-jail —
that would defeat the test (the test is whether the GATEWAY
catches the bad path before the fixture sees it). The fixture's
job is to be a dumb reader the gateway guards.

#### `mcp_mw_secrets_fixture.py` — security-middleware scrubbing fixture

A one-screen stdio MCP server used exclusively by
§Verification step 23. It exposes exactly one tool that returns
a deterministic string containing one of each secret pattern
class, so the verifier can assert every pattern is redacted:

* **`emit_secrets() -> str`** — takes no arguments, returns a
  `TextContent` item whose `text` is the fixed string below.
  The string is a verbatim constant in the fixture source (not
  generated), so the verifier's assertions are stable.

The fixture MUST return this exact text (byte-for-byte; the
verifier greps for the literal substrings):

```
AWS key: AKIA1234567890ABCDEF
GitHub token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789
Connection string: mongodb://user:pass@host/db
Private key: -----BEGIN RSA PRIVATE KEY-----
Bearer token: Bearer abcdef0123456789
```

Tool-list shape:

```json
{"name": "emit_secrets",
 "description": "Return a string containing one secret per pattern class. For security-middleware scrubbing verification only.",
 "inputSchema": {"type": "object", "properties": {}, "required": []}}
```

The fixture MUST NOT perform any redaction itself — the gateway's
stage 5 (`scrub_call_tool_result`) is the unit under test. The
fixture's job is to emit known-bad content and let the gateway
catch it.

The example below is abbreviated for readability. The canonical
reference profiles are `profiles/hermes-vc-gateway.yaml` and
`profiles/smoke-test.yaml`; if the example and profile files ever
disagree, the committed profile files win.

```yaml
name: hermes-vc-gateway
description: >-
  Heavy MCP servers shared across the operator's agents — code-review-graph,
  DocumentDB, context7, pencil, shadcn, Astro, DeepWiki, and the
  compliance-hardened filesystem upstream (fs). Each agent declares
  one mcpServers entry pointing at this profile via
  X-Profile: hermes-vc-gateway.
# Optional tenants allowlist. When set:
#   - The profile is reachable only by callers that send X-Tenant
#     (or ?tenant=) with one of these values.
#   - The Kanban dispatcher (which sets $HERMES_TENANT on each
#     spawned worker) is the canonical caller; non-Kanban agents
#     must send X-Tenant manually.
#   - Omit the field entirely to mark the profile as wildcard
#     (legacy behaviour): headerless callers can still reach it.
# tenants: [business-a, business-b]
upstreams:
  - key: code-review-graph
    transport: stdio
    command: uvx
    args: ["code-review-graph", "serve"]
    env: {}
    call_timeout_seconds: 30

  - key: DocumentDB
    transport: stdio
    command: npx
    args: ["-y", "awslabs.documentdb-mcp-server@latest"]
    env:
      DOCUMENTDB_CONNECTION_STRING: "MongoDB connection string for the local DocumentDB instance"
    call_timeout_seconds: 15

  - key: context7
    transport: stdio
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
    env: {}
    call_timeout_seconds: 30

  - key: pencil
    transport: stdio
    command: "C:/Program Files/Pencil/pencil-mcp.exe"
    args: []
    env: {}
    call_timeout_seconds: 60

  - key: shadcn
    transport: stdio
    command: npx
    args: ["-y", "@shadcn-ui/mcp"]
    env: {}
    call_timeout_seconds: 30

  - key: Astro
    transport: streamable_http
    url: https://mcp.example.com/astro
    headers: {}
    env:
      ASTRO_TOKEN: "API token for Astro docs MCP server"
    call_timeout_seconds: 60

  - key: DeepWiki
    transport: streamable_http
    url: https://mcp.deepwiki.com/mcp   # streamable HTTP endpoint; the /sse path is the deprecated SSE transport
    headers: {}
    env: {}
    call_timeout_seconds: 60

  - key: fs
    transport: stdio
    command: python3
    args: ["-m", "irigate.mcp_filesystem"]
    env: {}
    fs:                                  # opaque to the gateway; serialised into $IRIGATE_UPSTREAM_CONFIG
      allowed_roots:
        - "$HERMES_KANBAN_WORKSPACE"
        - "~/.irigate/notes"
      blocked_patterns_extra: ["*.local.json"]
      max_file_size_mb: 10
      read_only: true
    call_timeout_seconds: 15
# Profile-level security middleware (see §Security middleware
# (defense-in-depth)). The block is optional; when present it sets
# the defaults for every upstream in this profile. The defaults
# below match the §EffectivePolicy default table. Operators who
# want a no-middleware profile set `enabled: false`.
#
# Per-upstream overrides go on the UPSTREAM ENTRY (see the
# `code-review-graph` entry below for an example), NOT under a
# `security.upstreams:` sub-key here. Precedence is documented in
# §Per-upstream override precedence: upstream-level > profile-level
# > EffectivePolicy default. The one exception is `enabled`: a
# profile-level `enabled: false` disables the middleware for EVERY
# upstream, overriding any upstream-level `enabled: true`.
security:
  enabled: true
  scrub_secrets_in_responses: true
  scrub_secrets_in_logs: true
  audit_all_tool_calls: true
  max_message_size: 10485760
  rate_limit_enabled: true
  global_rate_limit: 60
  per_tool_rate_limit: 30
  rate_limit_overrides: {}
  path_jail_enabled: true
  path:
    # Empty allowed_roots = the gateway's path-jail is a no-op for
    # upstreams that do not declare their own path.allowed_roots.
    # The §Filesystem upstream's OWN jail (fs.allowed_roots) still
    # applies regardless. Non-fs upstreams (DocumentDB,
    # code-review-graph, etc.) take path arguments rarely enough
    # that the default is to leave the gateway jail off and rely on
    # the upstream's own input handling.
    allowed_roots: []
    denied_patterns_extra: []
    allow_override: []
```

The next listing shows an upstream-level override. The
`code-review-graph` upstream turns off response scrubbing (its
output is source code, which trips the generic `key=` regex),
raises its per-tool rate limit (graph traversals are bursty),
and narrows the path-jail to the repo root. Every other
upstream in the profile inherits the profile-level `security:`
block unchanged.

```yaml
  - key: code-review-graph
    transport: stdio
    command: uvx
    args: ["code-review-graph", "serve"]
    env: {}
    call_timeout_seconds: 30
    security:                          # per-upstream override (precedence: upstream > profile > default)
      scrub_secrets: false            # source-code responses trip the generic key= regex; disable locally
      rate_limit_overrides:
        "traverse_*": 120             # graph traversals are bursty; raise from 30/min default
        "query_*": 120
      path:
        allowed_roots:
          - "${HERMES_KANBAN_WORKSPACE}"
```

The gateway binary does not embed these profiles. Reference copies live
in this repo under `profiles/`; the operator copies them to
`~/.irigate/profiles/` and edits them per environment.

### Shape of the gateway script

The skeleton's `FastMCP(...).add_tool(...)` from the prior revision
is pseudocode that won't run as written. The implementer picks one of
two working patterns:

* **`mcp.server.Server` with `@server.list_tools()` /
  `@server.call_tool()` decorators** wrapped in an `asyncio` SSE
  transport. This matches the SSE transport pair that most MCP
  clients use, so the gateway and the client agree on framing.
* **`mcp.server.fastmcp.FastMCP`** with
  `@mcp_server.list_tools()` /
  `@mcp_server.call_tool()` decorators. Higher-level, but requires
  care to mount on a hand-rolled SSE app that pins `/sse` +
  `/messages` rather than FastMCP's defaults.

Both patterns are available in the pinned `mcp == 1.27.1` runtime.
Prefer `mcp.server.Server` for explicit transport control unless the
transport round-trip spike proves FastMCP's mounted SSE app matches the
required `/sse` + `/messages?session_id=<id>` contract. The skeleton's
`server.add_tool(proxy.list_tools)` is replaced by decorator
registration against a real `server: Server` or `mcp_server: FastMCP`
instance.

### Per-upstream connection

```python
async def connect_upstream(
    name: str, cfg: dict, effective_env: dict[str, str],
    tenant: str | None, kanban_workspace: str | None,
) -> tuple[str, ClientSession, list[str]] | None:
    """Spawn one upstream MCP client. Return (name, session, tool_names) or None on failure.

    `name` is the upstream-key from the profile (e.g. 'DocumentDB').
    `cfg` is the raw dict from the gateway profile:
        command/args/env  -> StdioServerParameters(env={
            **filtered_os_env, **cfg.env, **effective_env,
            **({'HERMES_TENANT': tenant} if tenant else {}),
            **({'HERMES_KANBAN_WORKSPACE': kanban_workspace}
              if kanban_workspace else {}),
        })
        url + transport:sse -> sse_client(url, headers={
            **base_headers,
            **({f'X-Hermes-Tenant': tenant} if tenant else {}),
            **({f'X-Hermes-Kanban-Workspace': kanban_workspace}
              if kanban_workspace else {}),
        })
        url + transport:streamable_http -> streamablehttp_client(url, headers=…) same shape
        (anything else -> raise GatewayConfigError at startup)
    `effective_env` is the per-session env-override dict for THIS upstream
        (only entries whose key matches `name`; see Fork semantics). For
        stdio upstreams it is merged into the subprocess env (between
        `cfg.env` and the `HERMES_*` overrides so caller-supplied values
        still win); for sse / streamable_http upstreams it is converted
        to outbound headers via `http_env_headers()` (see §HTTP/SSE
        upstreams): token-suffixed vars become an Authorization header
        with Bearer scheme; others become `X-Env-<VAR>: <value>`.
    `tenant` / `kanban_workspace` come from `SessionState`. They are
        forwarded to stdio subprocesses as `HERMES_TENANT` /
        `HERMES_KANBAN_WORKSPACE` (canonical Kanban env names) and to
        HTTP upstreams as `X-Hermes-Tenant` / `X-Hermes-Kanban-Workspace`.
        See §Tenant forwarding for the full contract.
    """
```

`name` (the upstream-key) is the routing prefix used by the SSE
handler. Failed `initialize` logs a warning and skips the upstream;
the remaining upstreams register normally.

### Reverse-proxy core

```python
class Gateway:
    def __init__(self, profiles: dict[str, Profile]):
        self.profiles = profiles
        self.fork_pools: dict[str, dict[str, ForkedInstance]] = {}
        self.http_session_pools: dict[str, dict[str, HttpSessionInstance]] = {}
        self.upstream_locks: dict[str, asyncio.Lock] = {}
        self.sessions: dict[str, SessionState] = {}

    async def list_tools(
        self, session_id: str, server_key: str | None
    ) -> ListToolsResult:
        # Resolve the session's profile/effective_env from self.sessions.
        # If server_key is None: union all upstreams in the profile,
        # initializing them on first use so their tool lists are known.
        # If server_key is set: tools for that upstream only.
        ...

    async def call_tool(
        self, session_id: str, server_key: str | None,
        tool_name: str, arguments: dict
    ) -> CallToolResult:
        # Pick the upstream for the tool. server_key when present
        # (Hermes convention); otherwise route by tool-name match
        # across all upstreams in the session. If more than one
        # upstream exposes the same tool, use first-upstream-wins
        # (profile declaration order) and log WARNING once per
        # (profile, tool_name, losing_upstream).
        async with self.upstream_locks[upstream_key]:
            return await session.call_tool(tool_name, arguments)

    # resources/list and resources/read are NOT proxied (Phase 1
    # non-goal). The gateway advertises an empty resources capability
    # in `initialize` and returns a JSON-RPC "method not found" error
    # for any resources/* call, so a client probing capabilities sees
    # a clean empty set instead of a hang or 404.
```

`session_id` is the per-SSE-connection identifier the gateway
assigns when an agent opens `/sse`. It is the key into
`Gateway.sessions`, whose value is the `SessionState` defined in
§SSE session registry. Fork pools remain keyed by
`(upstream_key, env_fingerprint)` and HTTP session pools remain keyed
by `(upstream_key, header_fingerprint)`; the session registry only
binds a client connection to its resolved profile and effective env.

`server_key` is `None` when the client does not send it (all
non-Hermes clients). The gateway routes by matching `tool_name`
against the upstream-tool map directly. Profile authors SHOULD keep
tool names unique, but collisions are deterministic: first upstream in
profile declaration order wins, and the gateway logs a WARNING naming
the profile, tool, winning upstream, and losing upstreams (never tool
arguments or results).

### Lifecycle (idioms, not imports)

Four patterns, replicated as design idioms in the gateway script. No
code is imported from `hermes-bridge`; each pattern is described in
enough detail that the implementer can reproduce it in ~30 lines of
glue:

* **PID file keyed by port.** Write
  `~/.irigate/logs/mcp-gateway-<port>.pid` on daemon startup. `stop`
  reads the same path, sends SIGTERM, polls `os.kill(pid, 0)` in a
  0.5 s loop up to 5 s, then SIGKILLs survivors. Mirrors
  `hermes-bridge`'s `cli.py:22-28`.
* **`doctor` with three checks.** Locate the profiles dir; verify
  `mcp` + `starlette` + `uvicorn` imports resolve; non-fatally
  attempt `connect_upstream` for every upstream entry across every
  profile with an empty effective_env (warnings about failures,
  exit 0). NOTE: `doctor` probes **reachability**, not correctness.
  An upstream that declares a required credential (e.g. DocumentDB's
  `DOCUMENTDB_CONNECTION_STRING`) will FAIL `initialize` under
  `doctor` because doctor passes no `?env=` overrides — this is
  expected and is NOT a signal that the gateway is broken. `doctor`
  is useful for catching missing binaries (`uvx`/`npx` not on PATH),
  typoed commands, and unreachable HTTP URLs; it cannot validate that
  a credentialled upstream will work at call time. Read `doctor`
  output as "of the upstreams that need no secrets, which are wired
  correctly?"
* **Daemonize via `os.fork() + setsid()`.** Parent prints the URL
  and exits; child `setsid()`s, redirects stdout/stderr to a log
  file, writes the PID file, then runs the asyncio loop. Replaces
  the shell `&` wrapper from the prior revision, which lost logs
  and broke SIGTERM forwarding. **POSIX-only:** `os.fork()` and
  `setsid()` do not exist on native Windows. The gateway is
  developed and tested on the WSL host (POSIX); on native Windows
  the operator MUST run with `start --foreground` (no daemonization)
  or wrap the gateway in a service manager (NSSM, sc.exe, a
  scheduled task). The gateway detects a non-POSIX platform at
  startup and, if `start` is invoked without `--foreground`, prints
  a clear error pointing at `--foreground` rather than crashing on
  the missing `os.fork` attribute.
* **SIGTERM-poll-then-SIGKILL stop.** Same algorithm as any
  PID-by-port daemon, with
  `GRACEFUL_TIMEOUT_SECONDS = 5.0` and
  `POLL_INTERVAL_SECONDS = 0.1`.

### Launch wiring

The gateway's own argv parser is:

```
irigate_mcp_proxy.py [--profiles-dir DIR] [--host 127.0.0.1] [--port 8000]
                     [--log-level INFO]
                     <command>
```

`<command>` is one of:

* `start [--foreground]` — daemonize by default, foreground if
  `--foreground`. Preflight (doctor) runs unless `--skip-checks` is
  set. Daemon mode writes the PID file, redirects stdio to the log,
  and `setsid()`s. Foreground mode does none of those side effects:
  it stays attached to the terminal, logs to stderr, and writes no PID
  file.
* `stop` — SIGTERM via PID file, exit 0 when stopped or no PID,
  exit 2 on partial failure.
* `status` — print running PID + URL + log path + loaded profile
  count or "not running".
* `doctor` — run preflight standalone (no daemon).
* `restart` — `stop`; `start`.
* `version` — print the gateway version constant (`SERVER_VERSION`,
  currently `0.1.0`) and exit.

Default `command` is `start --foreground` if the operator runs no
subcommand (preserves the single-flag ergonomics from the prior
revision).

### Defaults

```python
PROFILES_DIR_DEFAULT = "~/.irigate/profiles/"
HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 8000
GRACEFUL_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.1
FORK_REAPER_GRACE_SECONDS = 1.0              # overridable via IRIGATE_REAPER_GRACE_SECONDS env var
MAX_FORKED_INSTANCES_PER_UPSTREAM = 16    # hard cap; TTL is the primary mechanism
UPSTREAM_TTL_SECONDS_DEFAULT = 300        # per-upstream override via profile
PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION   # from mcp.types; currently "2025-11-25", NOT hard-coded
SERVER_NAME = "irigate-mcp-proxy"
SERVER_VERSION = "0.1.0"                  # printed by `version` subcommand; bump per release
TOKEN_VAR_SUFFIXES = ("_TOKEN", "_API_KEY", "_SECRET")  # HTTP env→Bearer mapping; see §HTTP/SSE upstreams
PID_PATH_TEMPLATE = "~/.irigate/logs/mcp-gateway-{port}.pid"
LOG_PATH_TEMPLATE = "~/.irigate/logs/mcp-gateway-{port}.log"
INHERITED_OS_ENV_ALLOWLIST = frozenset({"PATH", "HOME", "USER", "LANG", "LC_ALL", "TZ"})
                                              # Default for `upstreams[i].inherit_os_env` when
                                              # the upstream entry omits the field. The shipped
                                              # profiles (hermes-vc-gateway.yaml, smoke-test.yaml)
                                              # declare inherit_os_env explicitly; this default
                                              # only fires for operator-authored new profiles.
ALLOW_NON_LOOPBACK = False               # opt-in via --allow-non-loopback flag
REQUIRE_AUTH_FOR_NON_LOOPBACK = True     # see §Network binding and auth
```

The `--host` value is rejected at startup when it is not loopback
(`127.0.0.1`, `::1`, `localhost`) AND `--allow-non-loopback` is not
set — a clear error referencing this spec's loopback-by-default
constraint, not a generic argparse failure. When
`--allow-non-loopback` IS set, `0.0.0.0` and any non-loopback IP
are accepted, but the gateway then refuses to start unless one of
`IRIGATE_AUTH_TOKEN` / `IRIGATE_AUTH_TOKENS_FILE` is configured (see
§Network binding and auth). Loopback binds never require auth.

### Environment variables

The gateway reads the following environment variables at startup.
Production variables use the `IRIGATE_*` prefix; test-only
variables use the underscore-prefixed `_TESTING_IRIGATE_*` form
(matching the operator's convention: underscore = internal, must
not be relied on by production code).

#### Production (`IRIGATE_*`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `IRIGATE_HOST` | `127.0.0.1` | Bind address. Overrides `--host`. `--allow-non-loopback` permits non-loopback values but never changes the default by itself. |
| `IRIGATE_PORT` | `8000` | Bind port. Overrides `--port`. |
| `IRIGATE_PROFILES_DIR` | `~/.irigate/profiles/` | Profiles directory. Overrides `--profiles-dir`. |
| `IRIGATE_LOG_LEVEL` | `INFO` | One of `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `IRIGATE_REAPER_GRACE_SECONDS` | `1.0` | Overrides `FORK_REAPER_GRACE_SECONDS` at process start. SIGTERM→SIGKILL grace for forked upstreams during reaping. |
| `IRIGATE_AUTH_TOKEN` | unset | Single shared bearer token. Clients send an Authorization header of the form "Bearer" plus the redacted token value on every request. HMAC-compare timing. Mutually exclusive with `IRIGATE_AUTH_TOKENS_FILE`. |
| `IRIGATE_AUTH_TOKENS_FILE` | unset | Path to a file with one token per line (rotation). Mutually exclusive with `IRIGATE_AUTH_TOKEN`. |
| `IRIGATE_REQUIRE_TLS` | `false` | If `true`, refuse to start without `IRIGATE_TLS_CERT` + `IRIGATE_TLS_KEY`. Refuses loopback bind (TLS on loopback is wasted CPU). |
| `IRIGATE_TLS_CERT` | unset | Path to PEM-encoded TLS certificate. Required when `IRIGATE_REQUIRE_TLS=true`. |
| `IRIGATE_TLS_KEY` | unset | Path to PEM-encoded TLS private key. Required when `IRIGATE_REQUIRE_TLS=true`. |
| `IRIGATE_HEALTHZ_PUBLIC` | `false` | If `true`, `/healthz` does not require auth (for unauthenticated liveness probes). Default: when auth is enabled, `/healthz` requires the same auth as `/sse`; loopback/no-auth deployments remain unauthenticated. |

The `IRIGATE_AUTH_TOKEN` value is a secret. The gateway reads it
at startup, holds it in memory only (never logged, never written
to the log file, never reflected in error messages), and validates
every incoming request against it. Rotating the token requires a
gateway restart — there is no SIGHUP-reload mechanism in this
spec.

#### Test-only (`_TESTING_IRIGATE_*`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `_TESTING_IRIGATE_TTL_SECONDS` | unset | Per-process TTL override. If set, every upstream uses this TTL regardless of the profile's `ttl_seconds`. Used by `pytest` to verify reaper behavior in seconds, not minutes. |
| `_TESTING_IRIGATE_MAX_FORKS` | unset | Per-process hard cap override. If set, replaces `MAX_FORKED_INSTANCES_PER_UPSTREAM` for this process. Used to verify the 429 path without spawning 17 real forks. |
| `_TESTING_IRIGATE_NO_DAEMON` | unset | Test seam used by pytest fixtures. It forces foreground-style in-process execution even if the CLI path being tested omits `--foreground`, and it also disables PID-file/log-file side effects so tests do not touch `~/.irigate/logs/`. Operators use `start --foreground`; the test harness may use `_TESTING_IRIGATE_NO_DAEMON` when it needs to exercise daemon-code branches without actually forking. |

Test-only variables MUST NOT appear in any production startup
script, systemd unit, launchd plist, or operator documentation
outside `docs/MCP-PROXY.md §Verification`. They are internal
seams for the test harness.

### Network binding and auth

The gateway binds loopback by default and refuses to start when
configured to bind a non-loopback address without authentication.
This is a defense-in-depth posture: loopback-only deployments need
no auth because the network namespace is trusted; non-loopback
deployments require a token because the network is not.

**Bind address selection** (highest precedence first):

1. `IRIGATE_HOST` environment variable.
2. `--host` CLI flag.
3. Default: `127.0.0.1`.

If the resolved bind address is loopback (`127.0.0.1`, `::1`, or
`localhost`), the gateway starts without requiring any auth
configuration. If the resolved address is non-loopback, the
gateway requires:

* `--allow-non-loopback` flag (explicit opt-in), AND
* One of `IRIGATE_AUTH_TOKEN` or `IRIGATE_AUTH_TOKENS_FILE`.

If both are missing, the gateway prints an error citing this
spec's §Network binding and auth and exits non-zero.

**Auth flow:**

* Client sends an Authorization header ("Bearer" plus the redacted
  token value) on every request
  to `/sse`, `/messages`, `/profiles`, `/profiles/<name>`,
  `/profiles/<name>/schema`, and (by default) `/healthz`.
* Gateway validates the token via `hmac.compare_digest()` against
  the configured token or token-file entries.
* Invalid / missing token → HTTP 401 with
  `WWW-Authenticate: Bearer` header. No body content (don't leak
  why the auth failed).
* Valid token → request proceeds to routing logic.

**TLS:**

The gateway terminates TLS directly only when `IRIGATE_REQUIRE_TLS=true`.
The default is to speak plain HTTP and let an external reverse
proxy (nginx, Caddy, ALB, Cloudflare) handle TLS termination in
front of the gateway. This is the recommended deployment shape:

```
internet ──[TLS]──► nginx/Caddy ──[plain HTTP loopback]──► irigate-mcp-proxy
```

Direct TLS termination on the gateway is for edge cases where the
operator cannot put a reverse proxy in front (serverless
deployments, direct cloud ingress with no sidecar available).
Mutual TLS (client-certificate verification) is NOT implemented in
Phase 1; see §Future enhancements.

**Auth and `?env=` semantics:**

When a client authenticates with a valid token, the gateway
honours `?env=<upstream-key>.<VAR>=<value>` overrides as documented
in §Routing contract. The token holder is trusted to fork any
upstream in the resolved profile with any declared env var. This
is by design: the token is the trust boundary. Operators who want
per-client restrictions must issue different tokens and route them
to different profiles (out of scope for this spec).

### AI agent setup

The gateway is a plain HTTP/SSE service. Each AI agent declares
one `mcpServers` (or equivalent) entry pointing at the gateway URL
with an `X-Profile` header (or `?profile=` query parameter). No
agent-specific integration is required; the gateway speaks
standard MCP-over-SSE.

The per-agent config recipes below are authoritative. For a new
agent or a custom client, the contract is:

* HTTP method, URL path, and JSON-RPC framing: standard MCP.
* Transport: `sse` (or `streamable_http` if the agent supports it).
* Authentication (when binding non-loopback): an Authorization
  header ("Bearer" plus the redacted token value).
* Profile selector: `X-Profile: <name>` header preferred, or `?profile=<name>` query.

The agent's mcpServers entry looks like:

```yaml
mcp_servers:
  <arbitrary-key>:        # e.g. "irigate" or "shared-mcp"
    url: http://<gateway-host>:<port>/sse
    transport: sse
    headers:
      X-Profile: hermes-vc-gateway
      # Authorization: "Bearer <token>" when binding non-loopback
```

Note: the entry name (`<arbitrary-key>` above) is **the agent's
local handle for this MCP server**, not the gateway's profile
name. The gateway reads `X-Profile`, not the entry name. The agent
picks `<arbitrary-key>` freely.

#### Per-agent recipes

Each agent stores its MCP config in a different file. The recipes
below cover the six MCP-aware HTTP/SSE clients the operator runs.
All of them produce the same gateway-side behaviour: opening
`/sse` with `X-Profile: hermes-vc-gateway`, sending JSON-RPC
`initialize`, and exposing the unioned tools.

**Claude Code** (config at `~/.claude/settings.json` or
`.mcp.json` in the project root):

```json
{
  "mcpServers": {
    "irigate": {
      "type": "sse",
      "url": "http://localhost:8000/sse",
      "headers": {
        "X-Profile": "hermes-vc-gateway"
      }
    }
  }
}
```

**Codex CLI** (config at `~/.codex/config.toml`):

```toml
[mcp_servers.hermes-vc-gateway]
type = "sse"
url = "http://localhost:8000/sse"
headers = { "X-Profile" = "hermes-vc-gateway" }
```

**OpenCode** (config at `~/.config/opencode/config.json`):

```json
{
  "mcp": {
    "hermes-vc-gateway": {
      "type": "sse",
      "url": "http://localhost:8000/sse",
      "headers": {
        "X-Profile": "hermes-vc-gateway"
      }
    }
  }
}
```

**Cline** (config at `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` on macOS, or the equivalent path on Linux/Windows):

```json
{
  "mcpServers": {
    "hermes-vc-gateway": {
      "url": "http://localhost:8000/sse",
      "transport": "sse",
      "headers": {
        "X-Profile": "hermes-vc-gateway"
      }
    }
  }
}
```

**Kilocode** (config at the Kilocode settings panel → MCP Servers → "Edit Global MCP", or `~/.kilocode/mcp.json`):

Status: **requires verification before claiming done**. Kilocode does
not natively speak SSE MCP, so this recipe depends on `mcp-remote` and
its header-forwarding syntax. The implementer must verify the exact
syntax in §Open questions; the block below is the intended shape, not a
proven command.

```json
{
  "mcpServers": {
    "hermes-vc-gateway": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/sse"],
      "env": {
        "X-Profile": "hermes-vc-gateway"
      }
    }
  }
}
```

Kilocode does not natively speak SSE MCP — the recipe uses
`mcp-remote` as a stdio-to-SSE bridge. `X-Profile` MUST become an HTTP
header on the outbound request to the gateway; if the installed
`mcp-remote` cannot do that, the Kilocode recipe is not supported in
Phase 1. Alternative: run the gateway with a local stdio adapter (out
of scope for this spec).

**Hermes Agent** (config at `~/.hermes/profiles/<your-profile>/config.yaml`,
in the `mcp_servers:` block):

```yaml
mcp_servers:
  hermes:
    url: http://localhost:8000/sse
    transport: sse
    headers:
      X-Profile: hermes-vc-gateway
      # Optional: forward a tenant selector (the value matches the
      # profile's tenants: allowlist). When this profile declares
      # tenants: [biz-a, biz-b], the gateway rejects this header
      # with 403 if it is missing or set to anything else. Leave
      # X-Tenant unset when the profile has no tenants: key.
      X-Tenant: biz-a
```

This is hand-edited into the profile; no tool or wizard writes
it. The operator opens the file, adds the block, restarts the
profile, and verifies. Kanban workers do not need to edit this block:
the dispatcher already sets `HERMES_TENANT` on the worker process and
the spawn-time wiring adds `X-Tenant` automatically (see
§Tenant forwarding).

**Custom script with tenant scope** (any `mcp` client):

```python
import os, urllib.parse
from mcp.client.sse import sse_client
from mcp import ClientSession

async def main():
    headers = {"X-Tenant": "biz-a"}
    if workspace := os.environ.get("HERMES_KANBAN_WORKSPACE"):
        # Forward the worker's workspace path so filesystem-based
        # upstreams operate on the right directory.
        headers["X-Kanban-Workspace"] = workspace
    async with sse_client(
        url="http://localhost:8000/sse?profile=hermes-vc-gateway",
        headers=headers,
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            # use the unioned tools from all 8 upstreams
```

#### Discovery timeout

Some agents time out MCP server discovery at 1.5 s by default.
That can be too short for the gateway to initialize every upstream in
the selected profile during `tools/list` discovery (some stdio
upstreams cold-start via `npx` / `uvx`). Raise the agent's MCP
discovery timeout to ~5 s.

The setting name differs per agent:

* **Hermes Agent:** `mcp_discovery_timeout: 5` in
  `~/.hermes/profiles/<your-profile>/config.yaml`.
* **Claude Code:** no public knob; the connection timeout is
  controlled by the SSE transport library (~10 s default). No
  action required for Claude Code.
* **Codex / OpenCode / Cline / Kilocode:** consult each agent's
  docs for the equivalent timeout knob; if none exists, the
  default is typically long enough.

Operators running a one-upstream profile (e.g. `smoke-test.yaml`)
do not need to tune the timeout; spawning one stdio upstream fits
within the 1.5 s default.

**Custom Python script** (any `mcp` client):

```python
import os, urllib.parse
from mcp.client.sse import sse_client
from mcp import ClientSession

async def main():
    async with sse_client(
        url="http://localhost:8000/sse?profile=hermes-vc-gateway",
        headers={"X-Profile": "hermes-vc-gateway"},
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            # use the unioned tools from all 8 upstreams
```

If the caller needs to inject a per-session credential:

```python
cred = urllib.parse.quote_plus(os.environ["DOCUMENTDB_CONNECTION_STRING"])
url = (
    "http://localhost:8000/sse"
    "?profile=hermes-vc-gateway"
    f"&env=DocumentDB.DOCUMENTDB_CONNECTION_STRING={cred}"
)
```

The gateway validates the env override against the
`hermes-vc-gateway` profile's schema (DocumentDB has
`DOCUMENTDB_CONNECTION_STRING` declared), stores it in the SSE
session's `SessionState`, and returns the SSE stream. No DocumentDB
subprocess is spawned until the session issues a `tools/call` that
routes to DocumentDB; that call creates/reuses only the matching
DocumentDB env-fingerprint fork. Other upstreams in the profile are
not re-created for this override.

## Verification

The implementer must run each step and capture output.

```bash
# 1. The gateway starts cleanly and binds 8000.
python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 --log-level INFO start --foreground &
GATEWAY_PID=$!
sleep 3
ss -ltn 'sport = :8000'
# Expect: LISTEN ... 127.0.0.1:8000 ... users:(("python3",pid=<GATEWAY_PID>,...))

# 2. /sse returns text/event-stream (NOT text/html).
# curl exits 28 after --max-time because SSE stays open; that is OK if
# headers were received and the content type is text/event-stream.
set +e
curl -sS -D /tmp/irigate_sse_headers -o /tmp/irigate_sse_body \
    --max-time 3 "http://localhost:8000/sse?profile=smoke-test"
CURL_STATUS=$?
set -e
test "$CURL_STATUS" = 0 -o "$CURL_STATUS" = 28
python3 - <<'PY'
from pathlib import Path
h = Path('/tmp/irigate_sse_headers').read_text().lower()
assert '200' in h.splitlines()[0], h
assert 'content-type: text/event-stream' in h, h
print('sse_headers_ok')
PY
# Expect: sse_headers_ok

# 3. Real MCP SSE round-trip: initialize + tools/list + tools/call.
# This is the authoritative transport check. Raw curl POST /messages is
# NOT sufficient because the MCP SSE stream announces a session-bound
# /messages?session_id=<id> endpoint.
python3 - <<'PY'
import anyio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client('http://localhost:8000/sse?profile=smoke-test') as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == 'irigate-mcp-proxy', init
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert 'echo' in names, names
            result = await session.call_tool('echo', {'message': 'roundtrip'})
            text = ''.join(getattr(part, 'text', '') for part in result.content)
            assert 'roundtrip' in text, result
            print('mcp_roundtrip_ok', names)

anyio.run(main)
PY
# Expect: mcp_roundtrip_ok [..., 'echo', ...]

# 4. /profiles lists available profiles (no secret content).
curl -sS http://localhost:8000/profiles
# Expect: {"profiles":[{"name":"hermes-vc-gateway",...},{"name":"smoke-test",...}]}

# 5. /profiles/<name>/schema lists accepted env-override pairs.
curl -sS http://localhost:8000/profiles/hermes-vc-gateway/schema
# Expect: {"env":[{"upstream":"DocumentDB","var":"DOCUMENTDB_CONNECTION_STRING",...},
#                  {"upstream":"Astro","var":"ASTRO_TOKEN",...}, ...]}

# 6. Any agent configured for the profile discovers and registers all
#    upstream tools. (Hand-edit your agent's mcpServers entry per
#    §AI agent setup; restart the agent; observe its logs.)
# Example for Hermes Agent with the hermes-vc-gateway profile:
tail -50 ~/.hermes/profiles/<your-profile>/logs/agent.log | grep -E "MCP:"
# Expect: "MCP: registered N tool(s) from 1 server(s)" where N >= 50
# Expect NO "Expected response header Content-Type to contain 'text/event-stream', got 'text/html'"
# Expect NO "MCP server '<key>' failed initial connection"

# 7. End-to-end: a tool call from any agent hits an upstream.
# Example for Hermes Agent:
grep "tool_call" ~/.hermes/profiles/<your-profile>/logs/agent.log | tail -5
# Expect: successful response.

# 8. Per-session env override spawns/reuses only the targeted upstream.
# Opening /sse validates and freezes the env but does NOT fork DocumentDB.
# The first tools/call against a DocumentDB tool creates the DocumentDB
# env-fingerprint fork; other upstreams are not recreated for this env.
# Replace list_collections with a real DocumentDB tool from tools/list if
# the upstream uses a different name.
python3 - <<'PY'
import anyio, urllib.parse
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    value = urllib.parse.quote_plus('mongodb://localhost:27017')
    url = 'http://localhost:8000/sse?profile=hermes-vc-gateway&env=DocumentDB.DOCUMENTDB_CONNECTION_STRING=' + value
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert 'list_collections' in names, names
            await session.call_tool('list_collections', {})
            print('documentdb_env_call_ok')

anyio.run(main)
PY
# Expect: documentdb_env_call_ok; logs show only DocumentDB created a new
# env-fingerprint fork for the override (not all 8 upstreams).

# 9. Same-host Claude Code client reaches the same profile.
#    (Run a one-shot Claude Code invocation against the same SSE endpoint
#     with the same X-Profile header; expect the same unioned tools.)
#    NOTE on tool naming: the gateway exposes tools under their ORIGINAL
#    upstream names (no <upstream-key>__ prefix — see §Constraints). Each
#    agent then renders them under its own mcpServers-key namespace, so
#    the names the agent sees are mcp__<mcpServers-key>__<original-tool>,
#    NOT mcp__DocumentDB__*. For the recipe below the mcpServers key is
#    "irigate", so expect e.g. mcp__irigate__list_collections (a real
#    DocumentDB tool surfaced unprefixed), not mcp__DocumentDB__*.
claude --mcp-config '{"mcpServers":{"irigate":{"type":"sse","url":"http://localhost:8000/sse","headers":{"X-Profile":"hermes-vc-gateway"}}}}' \
    --print "list MCP tools"
# Expect: tool list contains tools sourced from DocumentDB, code-review-graph,
#         etc., all prefixed mcp__irigate__ by Claude Code's own naming.

# 10. Invalid env override rejected with 400 + schema inline.
curl -sS -o /dev/null -w "bad_env=%{http_code}\n" \
    --max-time 3 "http://localhost:8000/sse?profile=hermes-vc-gateway&env=UnknownUpstream.SOMETHING=foo"
# Expect: 400; response body references /profiles/hermes-vc-gateway/schema

# 11. One upstream's fork dying does NOT block other upstreams.
# Start two SSE sessions: one against DocumentDB, one against code-review-graph.
# Kill the DocumentDB fork (via pkill -P $GATEWAY_PID -f documentdb).
# The code-review-graph SSE session continues to serve tool calls.

# 12. TTL reaper tears down an idle fork after ttl_seconds.
# Restart the gateway with _TESTING_IRIGATE_TTL_SECONDS=5 to shorten the
# TTL window (defined in §Environment variables). Use the real MCP SSE
# client so the env override binds to the correct session_id.
kill "$GATEWAY_PID" 2>/dev/null || true
_TESTING_IRIGATE_TTL_SECONDS=5 python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 start --foreground &
GATEWAY_PID=$!
sleep 3
python3 - <<'PY'
import anyio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    url = 'http://localhost:8000/sse?profile=smoke-test&env=echo.TEST_KEY=reaper_probe'
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool('echo', {'message': 'reaper_probe'})
            print('echo_call_ok')

anyio.run(main)
PY
# Expect: echo_call_ok
curl -sS http://localhost:8000/healthz | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['forks']>=1, d; print('forks_after_call', d['forks'])"
# Expect: forks_after_call >= 1
sleep 7   # > ttl_seconds (5)
curl -sS http://localhost:8000/healthz | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['forks']==0, d; print('forks_after_reap', d['forks'])"
# Expect: forks_after_reap == 0; logs show "reaped fork for upstream=echo".

# 13. Hard cap returns 429 Too Many Forks.
# Restart the gateway with _TESTING_IRIGATE_MAX_FORKS=2 to lower the
# hard cap (default 16) so the test finishes quickly. Each MCP client
# opens its own SSE session with a unique TEST_KEY; the call_tool is
# what forces the fork and triggers the cap.
kill "$GATEWAY_PID" 2>/dev/null || true
_TESTING_IRIGATE_MAX_FORKS=2 python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 start --foreground &
GATEWAY_PID=$!
sleep 3
python3 - <<'PY'
import anyio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def one(i: int):
    url = f'http://localhost:8000/sse?profile=smoke-test&env=echo.TEST_KEY=value_{i}'
    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool('echo', {'message': str(i)})
                print(f'iter={i} ok')
    except Exception as exc:
        text = str(exc)
        if i >= 3 and ('429' in text or 'Too Many Forks' in text):
            print(f'iter={i} capped')
        else:
            raise

async def main():
    for i in range(1, 5):
        await one(i)

anyio.run(main)
PY
# Expect: iter=1 ok, iter=2 ok, iter=3 capped, iter=4 capped.
# Restart the gateway without the test env var to restore normal cap.

# 14. SIGTERM is graceful.
kill "$GATEWAY_PID"
wait "$GATEWAY_PID"
# Expect: exit=0 within 5s. Foreground stderr shows "shutting down" +
#         per-fork "closed" lines.

# 15. doctor surfaces upstream failures without refusing to start.
~/.irigate/bin/irigate_mcp_proxy.py --port 8000 doctor
# Expect: exit=0; JSON report lists each upstream in each profile with
#         connected: true|false + initialize error if false.

# 16. Tenant-scoped profile selection.
# Restart the gateway foreground for the tenant tests, create a second
# profile that declares tenants: [test-tenant] so a headerless request
# is rejected and an X-Tenant header is required.
kill "$GATEWAY_PID" 2>/dev/null || true; sleep 2
python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 start --foreground &
GATEWAY_PID=$!
sleep 3
cat > ~/.irigate/profiles/tenant-scoped.yaml <<'YAML'
name: tenant-scoped
description: "Profile whose reachability requires X-Tenant"
tenants: [test-tenant]
upstreams:
  - key: echo
    transport: stdio
    command: python3
    args: ["-m", "irigate.mcp_smoke_echo"]
    env:
      TEST_KEY: "Test env var; supply distinct values via ?env=echo.TEST_KEY=value_N to force unique env_fingerprints."
    ttl_seconds: 30
    call_timeout_seconds: 10
YAML
# (The gateway caches profiles at startup, so the new tenant-scoped.yaml
# only takes effect on the next restart. Real operators edit profiles
# and run `irigate_mcp_proxy.py restart`; this test does the same.)
kill "$GATEWAY_PID" 2>/dev/null || true; sleep 2
python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 start --foreground &
GATEWAY_PID=$!
sleep 3
# Headerless request to the tenant-scoped profile reaches it without
# a tenant check (the gateway treats absent headers as "no preference").
# This is the legacy wildcard behaviour — Claude Code etc. do not send
# X-Tenant and the gateway must not refuse them. Verify the profile
# is reachable, then verify that an EXPLICIT but mismatched tenant
# header is rejected.
curl -sS -o /tmp/tenant_headerless.json -w "%{http_code}\n" \
    --max-time 3 "http://localhost:8000/sse?profile=tenant-scoped"
# Expect: 200 (SSE handshake starts; curl returns 28 after --max-time
# because the stream stays open — both 0 and 28 are acceptable).
# Then: mismatched tenant header must return 403.
curl -sS -o /tmp/tenant_403.json -w "%{http_code}\n" \
    --max-time 3 \
    -H 'X-Tenant: something-else' \
    "http://localhost:8000/sse?profile=tenant-scoped"
# Expect: 403; body contains "tenant_not_allowed".
# /profiles filtered by tenant shows the scoped profile when the
# matching tenant is supplied in the query, regardless of whether
# any other profiles exist.
curl -sS "http://localhost:8000/profiles?tenant=test-tenant" | python3 -c "import json,sys; d=json.load(sys.stdin); names={p['name'] for p in d['profiles']}; assert 'tenant-scoped' in names, names; print('profiles_filtered_ok', names)"
# Send a real MCP request with X-Tenant to confirm the full path works.
python3 - <<'PY'
import anyio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client(
        'http://localhost:8000/sse?profile=tenant-scoped',
        headers={'X-Tenant': 'test-tenant'},
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert 'echo' in names, names
            print('tenant_scoped_roundtrip_ok', names)

anyio.run(main)
PY
# Expect: profiles_filtered_ok ...; tenant_scoped_roundtrip_ok [..., 'echo', ...].

# 17. HERMES_TENANT + HERMES_KANBAN_WORKSPACE forwarding.
# Use the stdio echo upstream + its whoami_env inspection tool to confirm
# the gateway forwards an absolute path and a tenant string through to
# the subprocess env unmodified. Step 16 already left the gateway
# running on port 8000 with both smoke-test and tenant-scoped profiles.
SCRATCH=$(mktemp -d)
python3 - <<PY
import anyio, json
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client(
        'http://localhost:8000/sse?profile=smoke-test',
        headers={
            'X-Tenant': 'biz-a',
            'X-Kanban-Workspace': '${SCRATCH}',
        },
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert 'whoami_env' in names, names
            result = await session.call_tool('whoami_env', {})
            text = ''.join(getattr(p, 'text', '') for p in result.content)
            env = json.loads(text)
            assert env.get('HERMES_TENANT') == 'biz-a', env
            assert env.get('HERMES_KANBAN_WORKSPACE') == '${SCRATCH}', env
            print('tenant_forward_ok', env)

anyio.run(main)
PY
# Expect: tenant_forward_ok {'HERMES_TENANT': 'biz-a',
#         'HERMES_KANBAN_WORKSPACE': '<scratch>', 'TEST_KEY': null|str}.

# 18. Reject non-absolute workspace path.
curl -sS -o /tmp/workspace_bad.json -w "%{http_code}\n" \
    --max-time 3 \
    -H 'X-Kanban-Workspace: relative/path' \
    "http://localhost:8000/sse?profile=smoke-test"
# Expect: 400; body contains "workspace_path_must_be_absolute".

# 19. Cleanup scratch profile + gateway.
kill "$GATEWAY_PID" 2>/dev/null || true; sleep 2
rm -rf "$SCRATCH" ~/.irigate/profiles/tenant-scoped.yaml
~/.irigate/bin/irigate_mcp_proxy.py --port 8000 status
# Expect: "not running".

# 20. Filesystem upstream deny-list + path-jail end-to-end.
# Restart the gateway against a fresh profile that contains the fs
# upstream and a scratch directory. The fs upstream MUST be running
# (it ships at ~/.irigate/lib/irigate/mcp_filesystem.py once the
# implementer lands it; the verification step is what proves the
# upstream is wired correctly, not just present in the profile).
mkdir -p ~/.irigate/profiles
cat > ~/.irigate/profiles/fs-test.yaml <<'YAML'
name: fs-test
description: "Verification fixture for the fs upstream deny-list + path-jail contract."
upstreams:
  - key: fs
    transport: stdio
    command: python3
    args: ["-m", "irigate.mcp_filesystem"]
    env: {}
    fs:
      allowed_roots: ["__SCRATCH__"]
      max_file_size_mb: 1
      read_only: false
    call_timeout_seconds: 15
YAML
# Substitute the scratch path now so the upstream sees a literal
# absolute path. The literal "fs-test" is replaced below by the
# shell at startup so the YAML in the profile is portable.
SCRATCH_FS=$(mktemp -d)
sed -i "s|__SCRATCH__|$SCRATCH_FS|g" ~/.irigate/profiles/fs-test.yaml
# Plant a sensitive file and a symlink-escape attempt.
echo "AKIAIOSFODNN7EXAMPLE" > "$SCRATCH_FS/.env"
echo "-----BEGIN RSA PRIVATE KEY-----" > "$SCRATCH_FS/id_rsa"
ln -s /etc/passwd "$SCRATCH_FS/passwd_via_symlink"
echo "harmless" > "$SCRATCH_FS/notes.md"
python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 start --foreground &
GATEWAY_PID=$!
sleep 3
python3 - <<PY
import anyio, json
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client(
        'http://localhost:8000/sse?profile=fs-test'
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert 'read_file' in names, names

            # 20a. .env MUST be denied by the deny-list.
            try:
                r = await session.call_tool('read_file', {'path': '$SCRATCH_FS/.env'})
                text = ''.join(getattr(p, 'text', '') for p in r.content)
                raise AssertionError(f'.env was NOT denied: {text!r}')
            except Exception as exc:
                assert 'deny_list' in str(exc), exc

            # 20b. id_rsa MUST be denied.
            try:
                r = await session.call_tool('read_file', {'path': '$SCRATCH_FS/id_rsa'})
                text = ''.join(getattr(p, 'text', '') for p in r.content)
                raise AssertionError(f'id_rsa was NOT denied: {text!r}')
            except Exception as exc:
                assert 'deny_list' in str(exc), exc

            # 20c. notes.md MUST be allowed.
            r = await session.call_tool('read_file', {'path': '$SCRATCH_FS/notes.md'})
            text = ''.join(getattr(p, 'text', '') for p in r.content)
            assert 'harmless' in text, text

            # 20d. symlink escape MUST be denied (CVE-2025-53109 class).
            try:
                r = await session.call_tool('read_file', {'path': '$SCRATCH_FS/passwd_via_symlink'})
                text = ''.join(getattr(p, 'text', '') for p in r.content)
                raise AssertionError(f'symlink escape was NOT denied: {text!r}')
            except Exception as exc:
                assert 'path_jail' in str(exc) or 'deny_list' in str(exc), exc

            print('fs_deny_list_path_jail_ok', names)

anyio.run(main)
PY
# Expect: fs_deny_list_path_jail_ok [..., 'read_file', ...].
# The upstream's stderr (visible in the gateway's startup logs) MUST
# show one JSON-lines audit entry per call, with outcome=denied for
# the .env/id_rsa/symlink cases and outcome=allowed for notes.md.

# 21. Cleanup fs verification.
kill "$GATEWAY_PID" 2>/dev/null || true; sleep 2
rm -rf "$SCRATCH_FS" ~/.irigate/profiles/fs-test.yaml
~/.irigate/bin/irigate_mcp_proxy.py --port 8000 status
# Expect: "not running".

# 22. Security middleware: path-jail blocks path-traversal at the
# transport boundary (defense-in-depth on top of the §Filesystem
# upstream's own jail). The fixture uses the dedicated
# `mcp_mw_path_fixture.py` upstream (lands alongside
# mcp_smoke_echo.py per §Implementation) which exposes a single
# tool `read_path(path: str) -> str` that returns the file's
# content. The profile declares `security.path.allowed_roots`
# so the gateway's path-jail is active on the echo-like
# upstream.
SCRATCH_MW=$(mktemp -d)
mkdir -p ~/.irigate/profiles
cat > ~/.irigate/profiles/mw-test.yaml <<'YAML'
name: mw-test
description: "Verification fixture for the gateway-side security middleware."
upstreams:
  - key: pathfix
    transport: stdio
    command: python3
    args: ["-m", "irigate.mcp_mw_path_fixture"]
    env: {}
    call_timeout_seconds: 10
security:
  enabled: true
  path:
    allowed_roots: ["__SCRATCH_MW__"]
  scrub_secrets: true
  rate_limit_enabled: false   # disabled to isolate the path-jail test
YAML
sed -i "s|__SCRATCH_MW__|$SCRATCH_MW|g" ~/.irigate/profiles/mw-test.yaml
echo "harmless inside jail" > "$SCRATCH_MW/inside.md"
echo "harmless outside jail" > /tmp/mw_outside.md
ln -s /tmp/mw_outside.md "$SCRATCH_MW/escape_via_symlink"
python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 start --foreground &
GATEWAY_PID=$!
sleep 3
python3 - <<PY
import anyio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client('http://localhost:8000/sse?profile=mw-test') as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            assert 'read_path' in tools, tools

            # 22a. Path inside the jail MUST be allowed.
            r = await session.call_tool('read_path', {'path': '$SCRATCH_MW/inside.md'})
            text = ''.join(getattr(p, 'text', '') for p in r.content)
            assert 'harmless inside jail' in text, text

            # 22b. Path outside the jail MUST be denied with rule=path_jail.
            try:
                r = await session.call_tool('read_path', {'path': '/etc/passwd'})
                text = ''.join(getattr(p, 'text', '') for p in r.content)
                raise AssertionError(f'external path was NOT denied: {text!r}')
            except Exception as exc:
                assert 'path_jail' in str(exc), exc

            # 22c. Symlink-escape MUST be denied (CVE-2025-53109 class).
            try:
                r = await session.call_tool('read_path', {'path': '$SCRATCH_MW/escape_via_symlink'})
                text = ''.join(getattr(p, 'text', '') for p in r.content)
                raise AssertionError(f'symlink escape was NOT denied: {text!r}')
            except Exception as exc:
                assert 'path_jail' in str(exc), exc

            # 22d. Path-traversal `..` MUST be denied.
            try:
                r = await session.call_tool('read_path', {'path': '$SCRATCH_MW/../../etc/passwd'})
                text = ''.join(getattr(p, 'text', '') for p in r.content)
                raise AssertionError(f'path-traversal was NOT denied: {text!r}')
            except Exception as exc:
                assert 'path_jail' in str(exc), exc

            # 22e. Null byte in path MUST be denied.
            try:
                r = await session.call_tool('read_path', {'path': '$SCRATCH_MW/inside.md\x00.bak'})
                text = ''.join(getattr(p, 'text', '') for p in r.content)
                raise AssertionError(f'null-byte path was NOT denied: {text!r}')
            except Exception as exc:
                assert 'path_jail' in str(exc), exc

            print('mw_path_jail_ok')

anyio.run(main)
PY
# Expect: mw_path_jail_ok.
# The gateway's stderr log MUST show one JSON-lines audit entry
# per call, with outcome=allowed for 22a and outcome=denied
# with rule=path_jail for 22b/22c/22d/22e.

# 23. Security middleware: secret scrubbing.
# Uses `mcp_mw_secrets_fixture.py` (lands alongside mcp_smoke_echo.py
# per §Implementation) which exposes a single tool
# `emit_secrets() -> str` returning a string with embedded AWS keys,
# GitHub tokens, a connection string, a PEM header, and a bearer
# token. The verifier asserts the gateway forwards the response
# with every detected secret replaced by `[REDACTED]`, and that
# the gateway's stderr log records the match class but NOT the
# matched value.
kill "$GATEWAY_PID" 2>/dev/null || true; sleep 2
cat > ~/.irigate/profiles/mw-secrets.yaml <<'YAML'
name: mw-secrets
description: "Verification fixture for the secret scrubbing middleware."
upstreams:
  - key: secfix
    transport: stdio
    command: python3
    args: ["-m", "irigate.mcp_mw_secrets_fixture"]
    env: {}
    call_timeout_seconds: 5
security:
  enabled: true
  scrub_secrets: true
  rate_limit_enabled: false
YAML
python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 start --foreground &
GATEWAY_PID=$!
sleep 3
LOG_BEFORE=$(wc -l < ~/.irigate/logs/mcp-gateway-8000.log)
python3 - <<'PY'
import anyio, re
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client('http://localhost:8000/sse?profile=mw-secrets') as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r = await session.call_tool('emit_secrets', {})
            text = ''.join(getattr(p, 'text', '') for p in r.content)

            # Every detected pattern MUST be replaced.
            assert 'AKIA1234567890ABCDEF' not in text, text
            assert 'ghp_' not in text, text
            assert 'mongodb://user:pass@host/db' not in text, text
            assert '-----BEGIN RSA PRIVATE KEY-----' not in text, text
            assert 'Bearer abcdef0123456789' not in text, text
            # The literal [REDACTED] marker MUST appear at least 5 times
            # (one per pattern class; base64 + generic are not in the fixture).
            assert text.count('[REDACTED]') >= 5, text
            print('mw_secret_scrub_ok redactions=', text.count('[REDACTED]'))

anyio.run(main)
PY
# Expect: mw_secret_scrub_ok redactions=...
# The gateway's stderr log (LOG_BEFORE..) MUST contain a
# `secret_scrubbed` audit entry per match. The original secret
# values MUST NOT appear in the log.
LOG_AFTER=$(wc -l < ~/.irigate/logs/mcp-gateway-8000.log)
if grep -E 'AKIA1234567890ABCDEF|ghp_|mongodb://user:pass|BEGIN RSA PRIVATE KEY' \
        <(sed -n "${LOG_BEFORE},${LOG_AFTER}p" ~/.irigate/logs/mcp-gateway-8000.log); then
    echo "FAIL: secret values leaked into stderr log"
    exit 1
fi
echo "mw_secret_log_clean_ok"

# 24. Security middleware: rate limit.
# Restart with a low per-tool limit so the test is fast. The fixture
# upstream exposes a single `repeat(message: str) -> str` tool (same
# pattern as `echo`). The verifier fires 35 calls in 2 seconds with
# a per-tool limit of 30/min and expects the last 5 to return
# `rate_limited` JSON-RPC errors.
kill "$GATEWAY_PID" 2>/dev/null || true; sleep 2
cat > ~/.irigate/profiles/mw-rate.yaml <<'YAML'
name: mw-rate
description: "Verification fixture for the rate limiter."
upstreams:
  - key: echo
    transport: stdio
    command: python3
    args: ["-m", "irigate.mcp_smoke_echo"]
    env: {}
    call_timeout_seconds: 5
security:
  enabled: true
  rate_limit_enabled: true
  per_tool_rate_limit: 5   # low limit for fast CI
YAML
python3 ~/.irigate/bin/irigate_mcp_proxy.py \
    --profiles-dir ~/.irigate/profiles/ \
    --port 8000 start --foreground &
GATEWAY_PID=$!
sleep 3
python3 - <<'PY'
import anyio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client('http://localhost:8000/sse?profile=mw-rate') as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            allowed = 0
            limited = 0
            for i in range(10):
                try:
                    await session.call_tool('echo', {'message': str(i)})
                    allowed += 1
                except Exception as exc:
                    if 'rate_limited' in str(exc) or '32029' in str(exc):
                        limited += 1
            assert allowed == 5, f"expected 5 allowed, got {allowed}"
            assert limited == 5, f"expected 5 rate_limited, got {limited}"
            print("mw_rate_limit_ok allowed=5 limited=5")

anyio.run(main)
PY
# Expect: mw_rate_limit_ok allowed=5 limited=5

# 25. Cleanup security-middleware verification.
kill "$GATEWAY_PID" 2>/dev/null || true; sleep 2
rm -rf "$SCRATCH_MW" /tmp/mw_outside.md \
    ~/.irigate/profiles/mw-test.yaml \
    ~/.irigate/profiles/mw-secrets.yaml \
    ~/.irigate/profiles/mw-rate.yaml
~/.irigate/bin/irigate_mcp_proxy.py --port 8000 status
# Expect: "not running".
```

## Rollback

1. Stop the gateway: `kill $(cat ~/.irigate/logs/mcp-gateway-<port>.pid)`
   (or `pkill -f irigate_mcp_proxy.py`).
2. Revert each agent's `mcpServers` entry by hand. The agent's
   `mcpServers.<key>` block (whatever key you used — `hermes`,
   `irigate`, `shared-mcp`, etc.; the key is arbitrary per §AI agent
   setup) restores the agent's original behaviour when removed. Most
   agents are unaffected by removing the entry entirely — only the
   unioned upstream MCP tools disappear.
3. Remove the gateway script: `rm ~/.irigate/bin/irigate_mcp_proxy.py`.
4. Remove any operator-authored profiles from `~/.irigate/profiles/`
   if desired (the directory is gateway-private; nothing else
   reads it).

If the operator wants to keep the gateway but drop ONLY the
filesystem upstream (e.g. they no longer need filesystem access
from agents, or the upstream turned out to be too restrictive):

1. Stop the gateway: `kill $(cat ~/.irigate/logs/mcp-gateway-<port>.pid)`.
2. Edit `~/.irigate/profiles/hermes-vc-gateway.yaml` and remove
   the `fs` upstream entry (and the description's reference to
   it). Do NOT rename the profile; the agent's `X-Profile:
   hermes-vc-gateway` header still resolves.
3. Restart the gateway: `~/.irigate/bin/irigate_mcp_proxy.py
   --port 8000 start`. Verify the agent's `tools/list` count
   drops by the number of `fs` tools the upstream exposed (≈5).
4. Optionally remove the upstream binary:
   `rm ~/.irigate/lib/irigate/mcp_filesystem.py`.

This partial rollback is safe: the §Filesystem upstream contract
is additive to the existing 7 upstreams and removing it leaves
the other 7 untouched.

If the operator wants to keep the gateway but drop ONLY the
security middleware (e.g. a false-positive regex is blocking
legitimate work, or the per-tool rate limit is too tight for
their agent's call pattern):

1. Stop the gateway: `kill $(cat ~/.irigate/logs/mcp-gateway-<port>.pid)`.
2. Edit `~/.irigate/profiles/<name>.yaml` and either remove
   the `security:` block entirely (reverts to defaults) or
   set `security.enabled: false` (disables the middleware
   without losing the per-upstream override configuration).
   The gateway restarts with the middleware bypassed; the
   §Filesystem upstream's own enforcement still applies.
3. Restart the gateway: `~/.irigate/bin/irigate_mcp_proxy.py
   --port 8000 start`.
4. Optionally remove the middleware modules:
   `rm -rf ~/.irigate/lib/irigate/security/`. The gateway
   fails to start on a profile that declares a `security:`
   block after the modules are removed, so this step is
   paired with step 2.

This partial rollback is safe: the security middleware
is upstream-agnostic and additive to the §Filesystem
upstream's own enforcement. Removing the middleware does
not weaken the §Filesystem upstream (which has its own
deny-list + path-jail) and does not affect the other
7 upstreams (which declare no `security:` block).

The gateway is non-invasive — rollback is one stop + one
hand-edit per agent. No shared state to revert beyond the agent
config blocks the operator wrote.

## Open questions

The implementation contract above is intentionally complete enough to
start coding. The implementer must resolve only these remaining external
integration questions before claiming the feature done:

1. **Per-agent discovery timeout knobs outside Hermes.** Hermes uses
   `mcp_discovery_timeout: 5`. Verify whether Codex, OpenCode, Cline,
   and Kilocode expose equivalent knobs. If a client has no knob,
   document that its default timeout is sufficient or that the client
   cannot reliably use the 8-upstream profile.
2. **Kilocode / `mcp-remote` header forwarding.** The recipe in §AI agent
   setup uses `mcp-remote` because Kilocode does not natively speak SSE.
   Verify the exact `mcp-remote` syntax for forwarding `X-Profile` as an
   HTTP header. Do not assume placing `X-Profile` in the process `env`
   becomes an HTTP header unless the tool documents that mapping.

## Future enhancements (Phase 2+)

These are explicitly out of scope for this spec but documented
so the next iteration knows what was considered.

* **Hot token reload.** The gateway reads `IRIGATE_AUTH_TOKEN`
  once at startup. Rotating requires a restart. Future: SIGHUP-
  triggered reload of the token (or `IRIGATE_AUTH_TOKENS_FILE`
  polled every N seconds). The file-based token list is the
  current workaround for rotation; operators write a script that
  swaps the file content and sends SIGHUP.
* **Per-client profile isolation.** Today every client with a
  valid bearer token gets the same profile set. Future: clients
  pass a `?profile=` (or `X-Profile`) at auth time and the token
  binds to a specific profile. Useful when one operator runs
  multiple isolated environments (e.g. staging vs production)
  behind a single gateway instance.
* **Dynamic upstream registration.** Today profiles are read once
  at startup. Future: `POST /profiles/<name>/upstreams/<key>` to
  add or update an upstream without a restart. Trade-off: makes
  the gateway's state mutable across requests, complicates the
  test surface, and conflicts with the per-upstream fork pool's
  reaping assumptions.
* **OAuth / mTLS.** Bearer token auth is sufficient for LAN and
  reverse-proxied deployments. Public-internet deployments need
  OAuth (per-user authz) or mTLS (mutual client-cert auth). Both
  require new dependencies (`authlib` for OAuth, more careful
  starlette routing for mTLS) and a credential-issuance story
  that the operator does not yet have.
* **Compliance audit log (Phase 2+).** The §Security middleware
  already emits a per-call JSON-lines record to stderr (stage 6,
  `audit_all_tool_calls: true` by default; see §Audit record
  contract). What remains for a compliance-grade trail: (a)
  wire `IRIGATE_AUDIT_HMAC_KEY` into `integrity.audit_fingerprint`
  so records become tamper-proof, not just tamper-detectable;
  (b) add an append-only file sink alongside stderr (the
  current sink is the gateway's log file, which rotates); (c)
  ship a queryable format (SQLite or Parquet) consumable by
  SIEM tooling. The Phase 1 record shape (ts, session_id,
  upstream, tool, args_hash, outcome, rule, tenant, workspace,
  duration_ms) is already the SIEM-ingest shape — the Phase 2
  work is transport and integrity, not schema.
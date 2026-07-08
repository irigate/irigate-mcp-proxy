# docs

## Purpose

Implementation specifications and durable design notes that the operator
hands to a future Hermes Agent session to implement. Each file in this
folder is a self-contained brief: a feature, the design decisions already
made, the contracts the implementation must honour, the verification it
must pass, and the rollback story. Files here are **not** reference docs
for the current state of `src/` — they describe **future** work.

## Ownership

- `*.md` files in this folder are implementation specifications.
- Each spec is read top-to-bottom by a single future Hermes session that
  is expected to implement, verify, and ship the change.
- The owning folder for the implementation lives **outside this repo**
  (for example `~/.hermes/...`, `~/.irigate/...`, a script under
  `~/.local/bin/`, an MCP server, etc.). This folder is the brief, not
  the workspace.
- Specs do not duplicate `AGENTS.md` contracts. If a rule already lives
  in a parent AGENTS.md, the spec references it; it does not restate it.

## Local Contracts

- **Filename is the feature name.** `MCP-PROXY.md` is the spec for the
  feature called "MCP proxy". Filenames are `UPPER-KEBAB.md`,
  imperative-noun when possible (`MCP-PROXY.md`, not `mcp-proxy-design.md`).
- **Frontmatter.** Every spec starts with YAML frontmatter containing
  at minimum: `title`, `status` (`draft | approved | in-progress |
  done | shelved`), `target` (the path the implementation will live at),
  `created`, and `session_id` (the Hermes session that authored the
  brief).
- **The reader is a fresh Hermes session.** It has the AGENTS.md
  contract and the rest of the DOX chain but **not** the conversation
  that produced this brief. Every design decision, every constraint,
  every diagnostic command must be in the file itself. The brief is
  the single source of truth for the future implementer.
- **Sections, in order:**
  1. `## Problem` — what is broken / missing today, with evidence
     (log lines, command output, error messages).
  2. `## Goal` — the desired end state in one paragraph.
  3. `## Non-goals` — what the implementation explicitly does NOT do.
  4. `## Constraints` — must-respect rules (security, operator
     preferences, hard wiring decisions).
  5. `## Design` — the architectural decision, including what was
     considered and rejected and why.
  6. `## Implementation` — exact paths to create/modify, function
     signatures, key behaviour. Enough that an implementer with the
     codebase open can write code without re-deciding.
  7. `## Verification` — the checks the implementer must run before
     claiming done, with expected output.
  8. `## Rollback` — how to revert if it breaks.
  9. `## Open questions` — anything the brief author did not decide;
     the implementer must resolve these before coding.
- **No "we" / "I" voice.** Specs are addressed to the future
  implementer ("the implementation must…", "the implementer should…").
  The author of the brief is anonymous unless the frontmatter
  `session_id` is queried.
- **Diagnostic commands are copy-pasteable.** Use fenced code blocks
  with the actual commands the implementer should run, not prose
  summaries.
- **Self-contained evidence.** Paste the exact log line / command
  output that proves the problem; do not paraphrase.
- **Update status, do not delete.** When a spec ships, flip
  `status: approved → in-progress → done` instead of removing the file.
  Git history carries the archive; the folder carries the living
  queue.

## Work Guidance

- Specs are written by the operator (or by Hermes on the operator's
  behalf in the current session) and consumed by a future Hermes
  session that may run in a different profile.
- Do not commit to design choices in the spec that the implementer
  cannot verify without re-running the diagnostic. If a constraint
  depends on a runtime check (e.g. "this is the only command that
  starts the gateway"), include the check.
- Cross-reference other specs by filename only (`see MCP-PROXY.md`),
  not by relative path. The implementer may run from any working
  directory.
- Keep specs terse. A spec that runs longer than the implementation
  is suspect.

## Verification

- Each spec's `## Verification` section is the implementer's
  acceptance test. The implementer runs every command listed and
  pastes the actual output (or the exit code) into the commit
  message / PR body / report-back message.
- A spec without a `## Verification` section is incomplete and
  must not enter `status: approved`.

## Child DOX Index

- `MCP-PROXY.md` — Standalone SSE MCP gateway (`irigate-mcp-proxy`)
  under `~/.irigate/bin/irigate_mcp_proxy.py`. Reads its own
  profiles from `~/.irigate/profiles/<name>.yaml`; never reads any
  agent's config (`~/.hermes/...`, `~/.claude/...`, `~/.codex/...`,
  etc.). Spawns each upstream as a stdio MCP client (or connects
  over SSE/streamable_http), and re-exposes the unioned `tools/list`
  and `tools/call` on a single SSE HTTP endpoint so any MCP-aware client (Hermes,
  Claude Code, Codex, OpenCode, Cline, Kilocode, custom script) can
  declare one `mcpServers` entry instead of one per upstream.
  Routing is
  profile-driven: `?profile=<name>` or `X-Profile: <name>` selects
  the upstream set; `?env=<upstream-key>.<VAR>=<value>` forks only
  the named upstream for the SSE session, leaving other upstreams in
  the profile shared. Tenant scoping is also profile-driven: an
  optional `tenants: [name, ...]` allowlist on a profile accepts
  `X-Tenant` (or `?tenant=`) inbound, with empty `tenants:`
  meaning "wildcard" (legacy behaviour for headerless callers);
  the gateway rejects mismatched tenant/profile pairs with HTTP 403
  listing the profiles that DO accept the value. The gateway also
  forwards `$HERMES_TENANT` (via inbound `X-Tenant` / `?tenant=`) and
  `$HERMES_KANBAN_WORKSPACE` (via inbound `X-Kanban-Workspace` /
  `?workspace=`) into stdio subprocess env and HTTP outbound headers
  (`X-Hermes-Tenant`, `X-Hermes-Kanban-Workspace`), so Hermes Kanban
  workers (which set those vars at spawn) can drive filesystem- or
  git-based MCP servers (code-review-graph, custom git MCPs) through
  the gateway without losing their tenant + workspace context.
  The §Filesystem upstream (compliance-hardened) section adds an
  8th upstream (`fs`) to the `hermes-vc-gateway` profile: a
  stdio filesystem MCP server that ships with its own deny-list
  (.env, .key, .pem, .ssh, id_rsa), path-jail with symlink
  awareness, and a JSON-lines audit hook. The deny-list /
  path-jail enforcement lives in the upstream itself, not the
  gateway; the gateway's role is to mount the upstream like any
  other stdio upstream and forward `$HERMES_KANBAN_WORKSPACE`
  as the upstream's per-session `allowed_root` when set.
  Loopback-by-default with `--allow-non-loopback`
  opt-in for non-loopback binds; non-loopback requires bearer auth
  via `IRIGATE_AUTH_TOKEN` or `IRIGATE_AUTH_TOKENS_FILE`. Optional
  TLS termination via `IRIGATE_REQUIRE_TLS` for edge deployments;
  reverse-proxy TLS recommended otherwise. Per-upstream `asyncio.Lock`
  + TTL-based reaper (default `ttl_seconds: 300`, hard cap 16 forks
  per upstream as emergency brake) keeps one slow upstream from
  blocking the others. Multiple ports allowed, each with its own PID
  file. Lifecycle (`start` / `stop` / `status` / `doctor` /
  `restart`) mirrors PID-by-port daemon patterns. Per-agent setup
  recipes in §AI agent setup.
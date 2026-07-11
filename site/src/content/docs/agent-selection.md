---
title: "Agent Selection"
navTitle: "Agent selection"
description: "Exact tool selection, upstream selectors, reverse selection, mixed semantics, and agent attribution."
seoDescription: "Configure Irigate client URLs with exact tools selection, upstream selection, reverse exclusions, mixed semantics, and agent labels."
order: 3
route:
  path: "/docs/agent-selection/"
  slug: "agent-selection"
source: "https://github.com/irigate/irigate-mcp-proxy/blob/main/IMPLEMENTATION.md"
---

Agent URLs connect to an already-running broker profile. They do not define profile fields such as `name` or `upstreams`.

## Exact tools selection

Use `tools=` for the narrowest and recommended path:

```text
http://127.0.0.1:8765/mcp?tools=context7__resolve-library-id,context7__query-docs
```

Exact tool selection activates only the referenced upstreams and exposes only the named tools. It never supports `!` exclusions because excluding one tool cannot avoid starting its upstream.

## Upstream selection

Use positive `upstreams=` selection when a client needs an upstream's complete tool surface:

```text
http://127.0.0.1:8765/mcp?upstreams=context7,code-review-graph
```

Omitting both `tools` and `upstreams` exposes all configured upstreams unchanged.

## Reverse selection

Prefix an upstream with `!` when the agent starts that MCP server directly and wants every other configured Irigate upstream:

```text
http://127.0.0.1:8765/mcp?upstreams=!code-review-graph
```

Reverse-only selection starts from all currently configured upstreams, so a profile reload can broaden it when a new upstream is added. Prefer `tools=` when least privilege matters.

## Mixed selection

Positive and reverse upstream selectors may be mixed. Positive names form the base set and exclusions are subtracted regardless of order:

```text
http://127.0.0.1:8765/mcp?upstreams=context7,code-review-graph,!code-review-graph
```

This selects only `context7`.

## Agent attribution

Add `agent=` to attribute valid tool calls in the runtime report:

```text
http://127.0.0.1:8765/mcp?upstreams=code-review-graph&agent=codex
```

Agent labels are metadata, not authentication. Omitted labels are grouped as `anonymous`, and Irigate does not infer identity from client headers.

## Rejected examples

These fail closed:

- Repeated selector parameters such as `?tools=a&tools=b`.
- Unknown upstream or tool names.
- Malformed selector tokens.
- Unrelated query parameters.
- Empty final selection sets.
- Invalid or repeated `agent` labels.

Continue with <a href="/docs/operations/">Operations</a> to inspect tools and runtime reports from the command line.

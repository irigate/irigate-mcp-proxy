---
title: "Getting Started"
navTitle: "Getting started"
description: "Install Irigate from a checkout, validate a profile, start the broker, and connect one selected client."
seoDescription: "Install Irigate from a repository checkout, validate a profile, start the loopback broker, and connect a client with tools selection."
order: 1
route:
  path: "/docs/getting-started/"
  slug: "getting-started"
source: "https://github.com/irigate/irigate-mcp-proxy/blob/main/README.md"
---

This path starts a loopback-only broker from a repository checkout and connects one client with the narrowest recommended selector.

## Requirements

- Python 3.11 through 3.14.
- [`uv`](https://docs.astral.sh/uv/) for installation and execution.
- Node.js with `npx` for the Context7 upstream in `profiles/mvp.yaml`.
- An installed `code-review-graph` executable if you select the isolated code-review-graph upstream.

The default profile starts no upstream process until an agent selects one. First selected use may download upstream package artifacts and require network access.

## Install from a checkout

From the repository root:

```bash
uv tool install --force --from . irigate
```

Ensure `~/.local/bin` is on `PATH`, then confirm the launcher works:

```bash
irigate --help
irigate --config profiles/mvp.yaml --check
```

For development, use the locked project environment instead:

```bash
uv sync --frozen
uv run --frozen irigate --config profiles/mvp.yaml --check
```

## Minimal profile

The smallest useful profile has a profile `name`, an `upstreams` map, and each upstream's command plus required idle timeout:

```yaml
name: local-development
upstreams:
  context7:
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
    idle_timeout_seconds: 300
```

Save it as a YAML file such as `profiles/local.yaml`.

## Validate without starting upstreams

Run:

```bash
irigate --config profiles/local.yaml --check
```

Validation rejects unknown fields, duplicate YAML keys, unsupported transports, invalid routing keys, non-loopback listeners, and missing environment references before any upstream starts.

## Start the broker

Run:

```bash
irigate --config profiles/mvp.yaml --require-qualified-sharing
```

The broker listens at `http://127.0.0.1:8765/mcp`. Stop it with `Ctrl+C`; shutdown drains active calls and closes child processes.

## Connect one client

Prefer exact tool selection for least privilege:

```text
http://127.0.0.1:8765/mcp?tools=context7__resolve-library-id,context7__query-docs
```

This URL connects to the already-running profile and exposes only those namespaced tools. It does not repeat the profile's `name` or `upstreams` fields as query parameters.

## Next links

Read <a href="/docs/configuration/">Configuration</a> for profile fields and reload behavior, then <a href="/docs/agent-selection/">Agent selection</a> for exact tool and upstream selector semantics.

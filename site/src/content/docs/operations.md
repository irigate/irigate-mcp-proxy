---
title: "Operations"
navTitle: "Operations"
description: "Operational commands for tool discovery, direct calls, reports, qualification, serving, reload, and shutdown."
seoDescription: "Operate Irigate with tools, call, ps, qualify, serving, reload behavior, shutdown, and metadata-only runtime reports."
order: 4
route:
  path: "/docs/operations/"
  slug: "operations"
source: "https://github.com/irigate/irigate-mcp-proxy/blob/main/README.md"
---

Irigate's command-line operations are designed for local validation, selected tool discovery, direct tool calls, process inspection, qualification, serving, reload, and shutdown.

## Serve

Start the broker in the foreground:

```bash
irigate --config profiles/mvp.yaml --require-qualified-sharing
```

The broker listens at the configured loopback address and starts upstreams only when selected.

## Discover tools

List namespaced tools available from a profile:

```bash
irigate tools --config profiles/mvp.yaml
```

This is runtime discovery, not static validation. It initializes every configured upstream, may download packages, may use the network, may require referenced environment variables, prints one `<upstream>__<tool>` name per line, then closes discovery workers.

## Call one tool

Invoke one namespaced tool without opening the HTTP listener:

```bash
irigate call --config profiles/mvp.yaml \
  code-review-graph__build_or_update_graph_tool \
  --arguments '{"repo_root":"/path/to/project","full_rebuild":false}'
```

`--arguments` accepts one JSON object and defaults to `{}`. The upstream starts only for this call and closes before the command exits. Credentials remain broker-process environment values and must not be supplied in tool arguments.

## Inspect runtime state

Read the latest runtime report:

```bash
irigate ps --config profiles/mvp.yaml
irigate ps --config profiles/mvp.yaml --json
```

`ps` reads `runtime_report_path` without starting upstreams or resolving their environment references. The table shows upstream/agent rows with effective mode, live instances, activity state, idle time, timeout, calls, and failures. JSON mode returns the complete schema-version-3 report.

## Qualify sharing

Run qualification for a configured profile:

```bash
irigate qualify --config profiles/mvp.yaml
```

Sharing admission combines generic protocol checks with a reviewed upstream-specific qualifier. Use <a href="/docs/configuration/">Configuration</a> for sharing fields and <a href="/docs/safety/">Safety</a> for the isolation boundary.

## Reload and shutdown

Profile reloads are connection-preserving for successful active-upstream changes. Invalid reloads leave the last valid configuration active. Stop the foreground broker with `Ctrl+C`; shutdown drains active calls and closes child processes.

## Troubleshooting links

- Use `--check` when you only need profile validation without upstream startup.
- Use <a href="/docs/agent-selection/">Agent selection</a> when a client exposes too many or too few tools.
- Use <a href="/docs/safety/">Safety</a> when deciding whether an upstream can be shared.

---
title: "Documentation"
navTitle: "Docs"
description: "Task-oriented Irigate documentation for local setup, configuration, selection, operations, safety, and FAQ."
seoDescription: "Irigate documentation for getting started, configuration, agent selection, operations, safety boundaries, and FAQ."
order: 0
route:
  path: "/docs/"
  slug: ""
source: "https://github.com/irigate/irigate-mcp-proxy/blob/main/IMPLEMENTATION.md"
---

Irigate is a loopback-only MCP broker for local developer workflows. It lets multiple local AI coding-agent sessions share explicitly qualified stdio MCP servers while preserving isolated-by-default behavior and metadata-only operational reports.

## First local run

Start with <a href="/docs/getting-started/">Getting started</a> to install Irigate from a checkout, create a minimal profile, validate it, start the broker, and connect one client with an exact `tools=` selector.

## Documentation pages

- <a href="/docs/getting-started/">Getting started</a> covers requirements, install, validation, serving, a selected client URL, and shutdown.
- <a href="/docs/configuration/">Configuration</a> explains broker fields, upstream fields, credential references, reload behavior, and sharing modes.
- <a href="/docs/agent-selection/">Agent selection</a> describes `tools=`, `upstreams=`, reverse selection, mixed selection, and `agent=` attribution.
- <a href="/docs/operations/">Operations</a> covers `tools`, `call`, `ps`, `qualify`, serving, reload, runtime reports, and shutdown.
- <a href="/docs/safety/">Safety</a> states the loopback boundary, Origin policy, credential rules, telemetry exclusions, and non-goals.
- <a href="/docs/faq/">FAQ</a> answers common MCP broker, sharing, cloud, gateway, compatibility, and latency questions.

## Contributor source

The public site is hand-synchronized from repository source documents. Contributors should use the root [implementation contracts](https://github.com/irigate/irigate-mcp-proxy/blob/main/IMPLEMENTATION.md), [README](https://github.com/irigate/irigate-mcp-proxy/blob/main/README.md), and [market research](https://github.com/irigate/irigate-mcp-proxy/blob/main/MARKET-RESEARCH.md) as authoritative behavior and evidence sources.

---
title: "Safety"
navTitle: "Safety"
description: "Loopback boundary, Origin checks, sharing admission, credential rules, telemetry exclusions, and non-goals."
seoDescription: "Irigate safety boundaries: loopback-only serving, Origin enforcement, qualified sharing, no request-delivered credentials, and metadata-only telemetry."
order: 5
route:
  path: "/docs/safety/"
  slug: "safety"
source: "https://github.com/irigate/irigate-mcp-proxy/blob/main/IMPLEMENTATION.md"
---

Irigate is a local broker with explicit boundaries. It should not be described as a general security, compliance, or enterprise governance product.

## Loopback only

The broker accepts only `localhost` or IP loopback listener addresses. Streamable HTTP requests reject malformed and non-loopback `Origin` headers to reduce DNS-rebinding risk. Local non-browser clients may omit `Origin`.

## Isolated by default

Non-shareable workers are scoped to downstream sessions and are never reused across sessions. Shared workers are reused only inside one broker process and only after qualification.

MCP transport behavior cannot prove semantic sharing safety. A shareable upstream needs explicit configuration and a reviewed qualifier. Unknown or unqualified upstreams remain isolated.

## No request-delivered credentials

Credentials must not be accepted through URLs, query parameters, command arguments, logs, or committed profiles. Runtime configuration may reference broker-process environment variables with `${ENV_NAME}`.

## Metadata-only telemetry

Audit records contain metadata such as timestamp, upstream key, tool name, duration, and outcome. Runtime reports contain process statistics, activity state, call counts, failures, and per-agent usage.

Arguments, results, environment values, commands, authorization headers, credentials, and hashes of low-entropy secrets are excluded from reports and audit records.

## Explicit non-goals

Irigate is not:

- An enterprise gateway.
- A remote access service.
- An identity or authorization layer.
- A Kubernetes control plane.
- A model API proxy.
- A compliance or DLP system.
- A public or multi-tenant MCP hosting service.

## Before sharing an upstream

Use isolated mode unless the upstream is fixed-identity, non-destructive, reviewed, and qualified for shared use. Benchmark identical and context-bound sessions separately; do not extrapolate a safe sharing result across credentials or workspaces.

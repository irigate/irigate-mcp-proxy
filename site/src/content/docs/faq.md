---
title: "FAQ"
navTitle: "FAQ"
description: "Visible answers to common questions about Irigate, MCP brokers, sharing, cloud services, gateways, clients, and latency."
seoDescription: "FAQ for Irigate: MCP broker basics, local server sharing, cloud behavior, gateway comparison, supported clients, and latency claims."
order: 6
route:
  path: "/docs/faq/"
  slug: "faq"
source: "https://github.com/irigate/irigate-mcp-proxy/blob/main/MARKET-RESEARCH.md"
---

These answers are visible HTML content and match the FAQ structured metadata.

## What is an MCP broker?

An MCP broker sits between MCP clients and MCP servers. Irigate exposes a local Streamable HTTP endpoint to AI coding agents and supervises configured stdio MCP upstreams behind it.

## Why share local MCP servers?

Several agent sessions can otherwise launch duplicate copies of the same stdio MCP server. When an upstream is safe to share, one broker-managed process can reduce duplicate child processes and resident memory on the workstation.

## Is every MCP server safe to share?

No. Some MCP servers retain client-specific state, credentials, workspace context, or other session assumptions. Irigate isolates upstreams by default and admits shared mode only when sharing is explicitly requested and qualified.

## Does Irigate send data to a cloud service?

Irigate does not require an Irigate cloud service. It runs locally and exposes a loopback endpoint. Configured upstream commands may use their own network services or package downloads, so review each upstream separately.

## Is Irigate an MCP gateway?

It is a local MCP broker and has protocol-forwarding overlap with gateways, but the MVP is not an enterprise gateway. It does not provide remote access, authenticated identity, RBAC, central administration, Kubernetes deployment, or model API proxying.

## How is it different from enterprise MCP gateways?

Enterprise gateways usually focus on managed deployment, identity, authorization, control planes, portals, and platform telemetry. Irigate focuses on local developer workstations, stdio process supervision, qualified sharing, and metadata-only local reports.

## Which coding agents work with it?

Current compatibility evidence validated one direct Streamable HTTP broker call from Hermes, Kilo/OpenCode, and Codex. Claude Code was installed but unavailable because the local CLI was not authenticated.

## Does it improve latency?

No latency improvement is claimed from the current evidence. The benchmark's Context7 calls were upstream-throttled, and an unthrottled 20-client diagnostic produced repeated 30-second timeouts and degradation.

---
title: Irigate — market hypothesis and competitive position
status: hypothesis
---

# Irigate — market hypothesis and competitive position

## Recommendation

Validate Irigate as a **local MCP broker for developers running multiple AI coding agents**. Do not position the current attempt as an enterprise compliance platform.

The plausible opportunity is narrow:

- Developers and small teams run several agent sessions on one workstation.
- Those sessions repeatedly start the same expensive stdio MCP servers.
- A local broker may reduce duplicate processes and repeated cold starts when the upstream is safe to share.
- A single local endpoint can also provide metadata-only visibility into tool usage across agent products.

This is a product hypothesis, not a proven market claim. Implementation should proceed only through the experimental gates in [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md).

## Category

Irigate fits best in **local AI developer infrastructure**, at the intersection of:

- MCP client/server connectivity
- Local process supervision
- Agent-tool observability
- Multi-agent workstation efficiency

It should not initially claim membership in broader enterprise categories such as AI Agent Governance, AI TRiSM, data-loss prevention, or enterprise MCP management. Those categories imply identity, authorization, durable evidence, central administration, deployment controls, and support obligations that the MVP deliberately does not provide.

## Developer problem

AI coding clients commonly launch stdio MCP servers as child processes. When several clients or worker sessions use the same configuration, the workstation can run duplicate instances of the same server and repeatedly pay initialization costs.

The problem is material only when all of the following are true:

1. Several agent sessions run concurrently.
2. At least one upstream has meaningful startup or resident-memory cost.
3. The upstream is safe to share between those sessions.
4. Sessions use compatible credentials, workspaces, and server state.
5. The broker adds less latency and operational complexity than it removes.

The previous “N agents × M upstreams becomes M processes” claim was too broad. Distinct credentials, workspaces, or state-isolation requirements can still require separate upstream instances. The implementation must measure realistic workloads rather than extrapolate from identical echo clients.

## Target user

Primary user:

> A developer or small platform team running multiple local AI coding-agent sessions across Hermes, Claude Code, Codex, or similar MCP clients, with one or more expensive stdio MCP servers.

The initial user is technically capable, accepts static configuration, and values lower workstation overhead more than a web control plane.

Not an initial target:

- Enterprise security teams buying a compliance control plane
- Organizations requiring Entra/OIDC identity and per-resource RBAC
- Central Kubernetes platform teams
- Public or multi-tenant MCP hosting providers
- Buyers seeking prompt-injection detection or general DLP

## Positioning statement

> Irigate is a loopback-only MCP broker that lets local AI coding agents share explicitly approved stdio MCP servers and records metadata-only tool-call telemetry. It is designed to reduce duplicate processes and cold starts without introducing a cloud control plane.

The words **explicitly approved** matter. MCP servers may retain client-specific state, so sharing must be opt-in and supported by isolation tests.

## Differentiation hypothesis

### 1. Workstation-local process consolidation

Most MCP gateways centralize remote traffic or deploy managed MCP servers. Irigate instead runs beside local coding agents and targets the duplicate stdio subprocesses created on one workstation.

This is the strongest potential differentiator, but it remains unproven until benchmarks demonstrate:

- Fewer child processes
- Lower resident memory
- Lower startup-to-first-tool latency
- No cross-session state leakage
- No unacceptable steady-state latency

### 2. Agent-independent local endpoint

A standards-based Streamable HTTP endpoint can serve different coding-agent products without reading or rewriting their private configuration formats. This gives one local integration point without coupling Irigate to a specific agent harness.

### 3. Metadata-only observability

A broker can record upstream, tool name, timing, outcome, and error class without retaining arguments or results. This can help developers understand tool reliability and bottlenecks while avoiding a high-risk payload collection system.

This is operational telemetry, not a compliance-grade audit trail.

## Microsoft MCP Gateway comparison

[Microsoft MCP Gateway](https://github.com/microsoft/mcp-gateway) is the clearest local comparison because it implements an MCP data plane, management APIs, authorization, deployment management, and a portal.

| Area | Irigate hypothesis | Microsoft MCP Gateway |
|---|---|---|
| Primary problem | Duplicate local stdio MCP processes | Central deployment and management of MCP servers and tools |
| Deployment | Developer workstation, loopback | Kubernetes and Azure-oriented infrastructure |
| Downstream transport | Streamable HTTP | Streamable HTTP |
| Upstream lifecycle | Local child processes, shared only by opt-in | Managed adapter/tool-server workloads |
| Identity | None in MVP; local OS boundary | Entra ID authentication |
| Authorization | None in MVP | Creator, administrator, and application-role checks |
| Session model | Local broker session mapped to selected upstream instances | Session affinity scoped to authenticated user and adapter |
| Control plane | Static configuration | REST management APIs and web portal |
| Telemetry | Metadata-only local JSON-lines | Platform logging and Application Insights integration |
| Best fit | Individual developers and small local teams | Enterprise platform and cloud operations teams |

The products overlap at protocol forwarding but solve different operational problems. Irigate should not attempt to reproduce Microsoft's control plane, Kubernetes lifecycle, identity model, portal, or Azure integrations.

A possible long-term relationship is complementary: Irigate handles local stdio processes at the developer edge, while a central gateway manages organization-hosted MCP services. That relationship is not part of the MVP and should not drive architecture before user evidence exists.

## Competitive groups

### Local MCP utilities

Examples include desktop MCP managers, stdio-to-HTTP bridges, and agent-specific MCP configuration tools. These are the closest functional substitutes because they operate on developer machines.

Irigate must beat them on measurable process reuse and multi-client correctness, not on a longer feature list.

### Enterprise and cloud MCP gateways

Examples include Microsoft MCP Gateway, Obot, Kong, Cloudflare, AWS gateway offerings, and other API-management vendors adding MCP support.

These products compete for central platform ownership. Their advantages include identity, policy integration, managed deployment, scaling, portals, and observability. Irigate should avoid this contest and remain a local edge component.

### Agent-native controls

Claude Code, GitHub Copilot, and other coding-agent products can provide permissions, managed settings, and product-specific logs. They are the default substitute because they require no additional local service.

Irigate is relevant only when a user runs several agent products or needs to consolidate MCP servers outside one vendor's process model.

### Security and DLP platforms

Endpoint DLP and AI security products inspect or control sensitive data across many channels. Irigate's MVP does not compete with them. Regex secret scanning and path guessing would not create a defensible DLP product and would introduce false positives and payload-handling risk.

## Deliberately rejected positioning

### “Enterprise compliance layer for agentic coding”

Rejected for the MVP because the design lacks:

- Authenticated user identity
- Per-resource authorization
- Multi-tenant isolation
- Durable and tamper-resistant evidence
- Central policy distribution
- Administrative workflows
- Formal security or compliance validation

### “Bidirectional secret protection”

Rejected because generic regex scanning cannot reliably distinguish legitimate tool credentials from exfiltration. Request-side blocking was disabled by default in the prior design, and response rewriting can corrupt valid source code or structured output.

The safer MVP rule is to avoid collecting arguments and results and to prohibit credentials in URLs, logs, and committed profiles.

### “Unified OpenAI and Anthropic governance gateway”

Rejected because model API proxying is a different, crowded product category and does not share the local stdio process-consolidation benefit. Adding it would weaken the developer-workstation focus.

### “Zero vendor lock-in, one binary”

Avoid this phrasing until packaging proves it. A Python application with an MCP SDK and external `npx`, `uvx`, or Python upstreams is not literally one dependency-free binary. The defensible claim is local deployment with open configuration and no required Irigate cloud service.

## Business model hypothesis

Start as an internal tool or open-source developer utility. Commercialization is premature until repeated use demonstrates a painful problem.

Potential later commercial surfaces, only after validation:

- Curated compatibility profiles for known-safe shared upstreams
- Fleet policy for workstation brokers
- Central collection of metadata-only health and performance metrics
- Supported enterprise packaging and update channels

Do not build these before evidence from real users. A local broker aimed only at individual developers may have strong utility but weak willingness to pay.

## Validation evidence required

The repository currently contains no implementation or benchmark evidence. Before making differentiation or market-size claims, collect:

| Evidence | Question answered |
|---|---|
| Process-count benchmark with 1, 5, and 20 clients | Does consolidation actually occur? |
| Resident-memory comparison | Is the saving material? |
| Cold-start and steady-state latency | Does the broker improve or degrade developer experience? |
| Shared-state isolation tests | Which upstreams are safe to share? |
| Distinct-workspace and distinct-credential tests | Do realistic contexts eliminate the saving? |
| Hermes, Claude Code, and Codex compatibility | Is agent independence real? |
| Multi-week operator usage | Is this painful enough to keep running? |
| Interviews with small platform teams | Is there demand beyond one workstation? |

Benchmark results must separate identical contexts from isolated contexts. Publishing only the best sharing case would misrepresent the product.

## Go/no-go decision

### Continue as a maintained local broker when

- At least one expensive, frequently used stdio upstream is safe to share.
- Real multi-agent workloads show repeatable and material resource or startup improvements.
- Streamable HTTP works with the target clients without a fragile bridge.
- The broker runs for normal development sessions without state leakage or orphan processes.

### Stop or reduce the project when

- Relevant upstreams require one process per client context.
- Savings disappear with realistic credentials and workspaces.
- Most target clients still require deprecated transport adapters.
- Agent-native process management solves the same problem adequately.
- Operators disable the broker because it adds troubleshooting complexity.

### Revisit commercial positioning only when

- Multiple independent teams use it continuously.
- A buyer, not only a developer, identifies a budgeted problem.
- Requested enterprise controls share the same architecture instead of turning Irigate into another generic API gateway.

## Current conclusion

Irigate is worth a bounded implementation attempt as a local MCP broker. It is not yet justified as an enterprise governance or compliance product.

The defensible niche is narrow but coherent: **shared local MCP infrastructure for developers running multiple coding agents**. The next investment should produce transport, isolation, and benchmark evidence—not additional policy features or market claims.

## References

- [Irigate implementation plan](IMPLEMENTATION-PLAN.md)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Microsoft MCP Gateway](https://github.com/microsoft/mcp-gateway)
- [Obot](https://obot.ai/)
- [Kong AI Gateway](https://konghq.com/products/kong-ai-gateway)
- [Cloudflare MCP documentation](https://developers.cloudflare.com/agents/model-context-protocol/)

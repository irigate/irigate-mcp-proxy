---
title: "Configuration"
navTitle: "Configuration"
description: "Profile fields, credential references, reload behavior, and sharing modes for Irigate."
seoDescription: "Irigate configuration guide covering broker fields, upstream fields, safe environment references, reload behavior, and sharing modes."
order: 2
route:
  path: "/docs/configuration/"
  slug: "configuration"
source: "https://github.com/irigate/irigate-mcp-proxy/blob/main/IMPLEMENTATION.md"
---

Irigate reads one YAML profile selected with `--config`. Profiles are validated before any upstream process starts.

## Broker fields

The profile requires `name` and a non-empty `upstreams` mapping. `host` defaults to `127.0.0.1`, `port` defaults to `8765`, and `runtime_report_path` is optional.

Only `localhost` or IP loopback listener addresses are accepted. The profile name labels validation output and runtime reports; it does not change routing.

## Upstream fields

Each upstream key becomes the prefix in `<upstream-key>__<tool-name>`. Keys must start with a lowercase letter and may contain lowercase letters, digits, and hyphens.

Supported upstream fields are `transport`, `command`, `args`, `env`, `shareable`, `qualifier`, `concurrency`, `call_timeout_seconds`, `idle_timeout_seconds`, `failure_threshold`, and `crash_threshold`. `transport` currently supports only `stdio`; `command` and `idle_timeout_seconds` are required.

Use the root [README configuration section](https://github.com/irigate/irigate-mcp-proxy/blob/main/README.md#configuration) for the complete field table.

## Credential references

Environment values must reference broker-process variables:

```yaml
env:
  CONTEXT7_API_KEY: ${CONTEXT7_API_KEY}
```

Do not put credentials in URLs, query parameters, command arguments, logs, or committed profiles. Irigate resolves the referenced value from the broker process without writing it into validation output, audit records, or runtime reports.

## Reload behavior

While serving, Irigate watches the selected profile. Changed active upstreams must initialize successfully before routing switches. Added and changed dormant upstreams remain stopped until selected.

Invalid updates, missing environment references, and failed upstream initialization leave the last valid active configuration available. Changes to `host` or `port` require restarting the broker.

## Sharing and isolation

Upstreams are isolated by default. `shareable: true` requests shared mode, but sharing is admitted only by a registered upstream-specific qualifier. Context7 is qualified shared in `profiles/mvp.yaml`; code-review-graph remains isolated because it retains context-bound state.

Failed qualification downgrades the selected upstream to isolated mode. With `--require-qualified-sharing`, the first selected use is rejected instead.

## Related pages

Use <a href="/docs/agent-selection/">Agent selection</a> to narrow what each client sees, and <a href="/docs/safety/">Safety</a> for the credential and telemetry boundary.

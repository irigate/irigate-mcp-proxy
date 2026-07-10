# Streamable HTTP round trip

Verdict: `VALIDATED`

## Candidate runtime

- Python: 3.14.4
- Official MCP Python SDK: 1.28.1
- HTTPX: 0.28.1

## Run

```bash
uv lock
uv run --frozen python verify.py
```

The verifier starts a loopback Streamable HTTP broker, which owns one persistent stdio echo-server session. It exercises `initialize`, `tools/list`, namespaced `tools/call`, simultaneous callers with deliberately inverted completion order, disconnect/reconnect, call timeout, Origin validation, and signal-based broker shutdown.

## Expected

```text
VALIDATED: initialize, tools/list, tools/call, two-client correlation, reconnect, timeout, Origin policy, graceful shutdown
```

## Origin policy

The SDK's DNS-rebinding middleware rejects malformed or non-loopback `Origin` values. A missing `Origin` is accepted because non-browser MCP clients do not necessarily send one; the `Host` header remains restricted to the configured loopback listener. Browser-originated requests must send an allowlisted loopback origin.

## Evidence

| Check | Result |
|---|---|
| Dependency resolution | `uv lock` resolved 32 packages |
| `initialize` | Passed for sequential and simultaneous clients |
| `tools/list` | Exposed exactly `echo__repeat` |
| `tools/call` | Returned each caller's unique value despite inverted delays |
| Disconnect/reconnect | A fresh client succeeded after the first session closed |
| Timeout | A one-second upstream delay failed under the 0.20-second broker bound |
| Origin policy | Remote and malformed origins returned 403; loopback and no-Origin requests returned 200 |
| Shutdown | SIGTERM produced `Application shutdown complete`; no SIGKILL was required |

Observed verifier output:

```text
VALIDATED: initialize, tools/list, tools/call, two-client correlation, reconnect, timeout, Origin policy, graceful shutdown
```

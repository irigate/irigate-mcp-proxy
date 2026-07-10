# Multi-client compatibility

Verdict: `VALIDATED`

## Candidate runtime

- Python: 3.14.4
- Official MCP Python SDK: 1.28.1
- Hermes Agent: 0.18.2 (2026.7.7.2)
- Kilo/OpenCode CLI: 7.3.54
- Codex App: installed per operator report; not discoverable from this WSL automation session
- Codex CLI: 0.142.4, login metadata present but runtime token refresh fails
- Claude Code: 2.1.87, installed but not authenticated

## Run

```bash
uv lock
uv run --frozen python verify.py
```

The verifier starts the spike-001 Streamable HTTP broker, creates temporary client configuration homes, and configures only the loopback broker endpoint. Hermes references its existing authentication file by symlink without reading it; Kilo/OpenCode uses its existing credential store while loading MCP configuration from a temporary XDG config home. Each invocation must increase the broker's metadata-only call count and return its unique marker. Temporary homes are removed after the run.

## Expected

```text
VALIDATED: Hermes and Kilo/OpenCode called Streamable HTTP directly; Claude and Codex unavailable (authentication)
```

## Evidence

| Client | Result |
|---|---|
| Hermes Agent | Called `echo__repeat` once through Streamable HTTP and returned `HERMES_STREAMABLE_OK` |
| Kilo/OpenCode | Called `echo__repeat` once through Streamable HTTP and returned `KILO_STREAMABLE_OK` |
| Claude Code | Not tested: installed client is not authenticated |
| Codex App / CLI | App installed per operator report; automated CLI tool call blocked because runtime token refresh fails |

The verifier checked the broker's metadata-only call count before and after each successful client run, so merely repeating the marker without a tool call would fail.

Observed verifier output:

```text
VALIDATED: Hermes and Kilo/OpenCode called Streamable HTTP directly; Claude and Codex unavailable (authentication)
```

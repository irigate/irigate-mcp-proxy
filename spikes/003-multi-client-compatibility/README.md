# Multi-client compatibility

Verdict: `VALIDATED`

## Candidate runtime

- Python: 3.14.4
- Official MCP Python SDK: 1.28.1
- Hermes Agent: 0.18.2 (2026.7.7.2)
- Kilo/OpenCode CLI: 7.3.54
- Codex App: installed per operator report; not discoverable from this WSL automation session
- Codex CLI: 0.144.1, ChatGPT login restored per operator update
- Claude Code: 2.1.87, installed but not authenticated

## Run

```bash
uv lock
uv run --frozen python verify.py
```

The verifier starts the spike-001 Streamable HTTP broker, creates temporary client configuration homes, and configures only the loopback broker endpoint. Hermes references its existing authentication file by symlink without reading it; Kilo/OpenCode uses its existing credential store while loading MCP configuration from a temporary XDG config home; Codex uses its existing authentication file by symlink without reading it. Each invocation must increase the broker's metadata-only call count and return its unique marker. Temporary homes are removed after the run.

## Expected

```text
VALIDATED: Hermes, Kilo/OpenCode, and Codex called Streamable HTTP directly; Claude unavailable (not authenticated)
```

## Evidence

| Client | Result |
|---|---|
| Hermes Agent | Called `echo__repeat` once through Streamable HTTP and returned `HERMES_STREAMABLE_OK` |
| Kilo/OpenCode | Called `echo__repeat` once through Streamable HTTP and returned `KILO_STREAMABLE_OK` |
| Codex CLI | Called `echo__repeat` once through Streamable HTTP and returned `CODEX_STREAMABLE_OK` |
| Claude Code | Not tested: installed client is not authenticated |

The verifier checked the broker's metadata-only call count before and after each successful client run, so merely repeating the marker without a tool call would fail.

Observed verifier output:

```text
VALIDATED: Hermes, Kilo/OpenCode, and Codex called Streamable HTTP directly; Claude unavailable (not authenticated)
```

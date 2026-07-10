# profiles

## Purpose

Validated static broker profiles used by the package, runtime qualification, and benchmark harnesses.

## Ownership

- `mvp.yaml` is the primary local profile: qualified shared Context7 plus isolated code-review-graph backed by the global `~/.code-review-graph/` datastore and registry.
- `benchmark-heavy.yaml` adds a third isolated upstream for resource and latency measurement.

## Local Contracts

- Profile files conform to `irigate.models.BrokerConfig` and contain no credential values.
- Environment entries, when needed, use `${ENV_NAME}` references resolved only from the broker process.
- The MVP code-review-graph upstream uses the installed `code-review-graph` executable directly and resolves the broker user's global `~/.code-review-graph/registry.json`; repository paths passed to its tools remain absolute.
- `shareable: true` entries name a registered upstream-specific qualifier.
- Every upstream declares `idle_timeout_seconds`; profiles do not rely on a hidden lifecycle default.
- Profiles bind to loopback and configure stdio upstreams only.

## Work Guidance

- Run `irigate --check` after every profile edit.
- Update `IMPLEMENTATION.md` when a profile change alters qualification, sharing, or benchmark contracts.

## Verification

- `uv run --frozen python -m irigate --config profiles/mvp.yaml --check`
- `uv run --frozen python -m irigate --config profiles/benchmark-heavy.yaml --check`

## Child DOX Index

- No child DOX files.

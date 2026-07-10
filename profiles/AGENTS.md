# profiles

## Purpose

Validated static broker profiles used by the package, runtime qualification, and benchmark gates.

## Ownership

- `mvp.yaml` is the primary local profile: qualified shared Context7 plus isolated code-review-graph.
- `benchmark-heavy.yaml` adds a third isolated upstream for resource and latency measurement.

## Local Contracts

- Profile files conform to `irigate.models.BrokerConfig` and contain no credential values.
- Environment entries, when needed, use `${ENV_NAME}` references resolved only from the broker process.
- `shareable: true` entries name a registered upstream-specific qualifier.
- Profiles bind to loopback and configure stdio upstreams only.

## Work Guidance

- Run `irigate --check` after every profile edit.
- Update the implementation plan when a profile change alters a qualification or benchmark gate.

## Verification

- `uv run --frozen python -m irigate --config profiles/mvp.yaml --check`
- `uv run --frozen python -m irigate --config profiles/benchmark-heavy.yaml --check`

## Child DOX Index

- No child DOX files.

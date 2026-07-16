# profiles

## Purpose

Validated static broker profiles used by the package, runtime qualification, and benchmark harnesses.

## Ownership

- `mvp.yaml` is the primary local profile: qualified shared Context7 plus isolated code-review-graph backed by the global `~/.code-review-graph/` datastore and registry.
- `benchmark-heavy.yaml` exercises Context7, GitHub, Git, filesystem, Windows and Linux browser tooling, Open Scaffold, and Astro documentation upstreams for resource and latency measurement.

## Local Contracts

- Profile files conform to `irigate.models.BrokerConfig` and contain no credential values.
- Shipped upstreams include concise descriptions so progressive metadata discovery is useful without process startup.
- Environment entries, when needed, use `${ENV_NAME}` references resolved only from the broker process.
- The MVP code-review-graph upstream uses the installed `code-review-graph` executable directly and resolves the broker user's global `~/.code-review-graph/registry.json`; repository paths passed to its tools remain absolute.
- Remote Streamable HTTP upstreams use a reviewed stdio bridge because the broker accepts stdio upstreams only.
- The benchmark filesystem, Git, and Open Scaffold upstreams require a per-session workspace under `${HOME}`. They remain non-shareable and use ordered scoped-to-global sources so one canonical workspace can populate every selected process.
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

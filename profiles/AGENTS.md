# profiles

## Purpose

Pre-implementation workload and smoke-test profiles used by the transport, isolation, and benchmark spikes.

## Ownership

- `hermes-vc-gateway.yaml` inventories representative heavy stdio upstreams for benchmark selection.
- `smoke-test.yaml` defines the credential-free echo fixture shape.
- Phase 1 of `IMPLEMENTATION-PLAN.md` replaces these design inputs with the validated runtime schema.

## Local Contracts

- Profile files contain configuration shape, descriptions, and environment-variable names; they do not contain credentials.
- Profile examples must remain aligned with `IMPLEMENTATION-PLAN.md`.
- Examples are safe to commit and contain no runtime credential values.

## Work Guidance

- Treat current profiles as experiment inputs, not production-ready configuration.
- Update the implementation plan when a profile change alters an experimental gate or intended contract.

## Verification

- Use the spike and benchmark gates in `IMPLEMENTATION-PLAN.md`.

## Child DOX Index

- No child DOX files.

# src

## Purpose

Production package source tree.

## Ownership

- `irigate/` owns the broker package and its runtime contracts.

## Local Contracts

- Production code must not import from `spikes/` or `tests/`.
- Public behavior is verified through the package entry point and tests.

## Work Guidance

- Put package-wide rules in `src/irigate/AGENTS.md`.

## Verification

- `uv run --frozen pytest -q`

## Child DOX Index

- `irigate/AGENTS.md` — Irigate package contracts and module ownership.

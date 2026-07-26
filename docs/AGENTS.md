# Release documentation

## Purpose

- `RELEASING.md` is the operator source of truth for production PyPI and GitHub releases.
- `releases/vX.Y.Z.md` is the exact body published for that GitHub Release.
- `releases/TEMPLATE.md` defines the minimum release-note structure.

## Ownership

- `RELEASING.md` owns the Trusted Publisher setup, release preparation, tag procedure, verification, and recovery guidance.
- `releases/` owns versioned release notes and their template.

## Local Contracts

- Releases are immutable, tag-driven deployments. A `vX.Y.Z` tag must match `src/irigate/__init__.py` and `pyproject.toml`, and the tagged commit must contain `releases/vX.Y.Z.md`.
- Keep setup instructions aligned with `.github/workflows/publish.yml`, the `pypi` GitHub environment, and PyPI Trusted Publisher fields.
- Release notes describe user-visible behavior, upgrade actions, compatibility, and known limitations; do not use raw commit lists.
- Never document or introduce a long-lived PyPI token when Trusted Publishing is available.

## Work Guidance

- Treat a PyPI name collision, a mismatched tag, missing release notes, or a failed artifact check as a stop condition before publishing.
- Do not move or recreate tags after PyPI accepts their version.

## Verification

- Run the repository verification commands in `RELEASING.md`.
- Validate relative links in all Markdown files.
- Confirm that the release-notes filename exactly matches the proposed tag.

## Child DOX Index

- No child `AGENTS.md` files.

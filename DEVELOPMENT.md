# Irigate development

The [README](README.md) is for installing and using the published package. This document covers source checkouts, repository verification, and release artifacts.

## Set up a checkout

Irigate supports Python 3.11 through 3.14 and uses [uv](https://docs.astral.sh/uv/) for its locked development environment.

```sh
git clone https://github.com/irigate/irigate-mcp-proxy.git
cd irigate-mcp-proxy
uv sync --frozen
uv run --frozen irigate --version
uv run --frozen pytest -q
```

Use an editable tool installation when testing the checkout through the installed console command:

```sh
uv tool install --editable .
irigate --version
```

Use `uv tool install --force --from . irigate` to exercise a fixed package snapshot. This does not track later source edits.

## Verify changes

Run these checks before submitting a change or preparing a release:

```sh
uv run --frozen pytest -q
uv run --frozen irigate --help
uv run --frozen irigate --config profiles/mvp.yaml --check
uv run --frozen irigate --config profiles/benchmark-heavy.yaml --check
uv build
uv run --frozen python -m twine check dist/*
```

The two profile checks validate configuration without starting their upstream processes. `uv build` writes a wheel and source distribution to `dist/`; both must pass `twine check`.

## Publish releases

Production releases are immutable, tag-driven deployments. Pushing `vX.Y.Z` runs GitHub Actions to test and build the distributions, publishes them to PyPI through OpenID Connect Trusted Publishing, then creates the matching GitHub Release with the exact artifacts. No long-lived PyPI token belongs in GitHub Secrets.

Follow [docs/RELEASING.md](docs/RELEASING.md) for the one-time PyPI and GitHub setup, version and release-note preparation, exact tag commands, verification, and failure recovery.

# Irigate website

Static Astro source for `https://irigate.io`.

## Local setup

Requires Node 24 and Corepack.

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
```

Use `pnpm check:types` for Astro and TypeScript validation, `pnpm build` for a production build, and `pnpm preview --host 127.0.0.1` to inspect `site/dist/` locally. `pnpm verify` runs the current deterministic local gate.

`pnpm-workspace.yaml` explicitly permits esbuild's required install script. Do not broaden that build allowlist without reviewing the dependency and the generated lockfile.

## Content ownership

Public copy belongs under `src/content/`. Keep it synchronized by hand with the authoritative behavior, architecture, and evidence in the root `README.md`, `IMPLEMENTATION.md`, and `MARKET-RESEARCH.md`; the build does not parse those files.

## Deployment

The production site is a root-hosted static build with `site: "https://irigate.io"` and no repository base path. GitHub Pages workflow and custom-domain operations are added in later implementation phases.
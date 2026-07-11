# site

## Purpose

Static Astro website for `https://irigate.io`, including product pages, public documentation, SEO endpoints, and deterministic built-output checks.

## Ownership

- `src/content/` owns substantive public product and documentation copy.
- Astro pages, layouts, components, and styles own routing and presentation.
- `public/` owns files copied directly into the deployed site.
- `scripts/` owns website-specific generation and built-output verification.
- Root `README.md`, `IMPLEMENTATION.md`, and `MARKET-RESEARCH.md` remain authoritative source material for behavior, architecture, and benchmark evidence.

## Local Contracts

- Keep output static and rooted at `https://irigate.io`; do not configure a repository `base` path.
- Keep product claims within the loopback-only broker boundary and measured evidence in the root documents.
- Hand-synchronize affected website content in the same change as changes to root behavior or evidence documents. Do not parse root Markdown at build time.
- Use Markdown for prose-heavy documentation and MDX only where reusable Astro components are needed.
- Use framework-free JavaScript only for concrete interactions such as theme preference and command copying.
- The theme preference key is `irigate.theme`; store only `light`, `dark`, or `system`, and apply the effective `light|dark` value as `data-theme` on the root element.
- Keep `site/dist/`, `site/.astro/`, and `site/node_modules/` generated and untracked.
- Keep dependency install scripts denied unless explicitly approved in `pnpm-workspace.yaml`; esbuild is the reviewed baseline exception required by Astro.
- Bind development and preview servers to loopback unless an operator explicitly chooses otherwise.

## Work Guidance

- Use semantic design tokens for both light and dark palettes; do not hard-code mode-specific colors in components.
- Preserve ordinary links, visible HTML content, keyboard operation, reduced-motion behavior, and readability without JavaScript.
- Reuse the generated brand SVGs from `assets/` without changing their geometry.

## Verification

- Run `corepack pnpm install --frozen-lockfile` from `site/`.
- Run `corepack pnpm check:types` and `corepack pnpm build` from `site/`.
- Run `corepack pnpm verify` once deterministic built-site assertions exist.
- Preview with `corepack pnpm preview --host 127.0.0.1`.

## Child DOX Index

None.

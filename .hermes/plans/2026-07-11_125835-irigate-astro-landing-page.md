# Irigate Astro landing page implementation plan

## Goal

Create a fast, accessible, SEO-focused Astro website in `site/`, publish it to GitHub Pages at `https://irigate.io`, and rebuild it whenever the website, Markdown/MDX content, shared brand assets, or deployment workflow changes. The site must be fully testable locally before deployment.

## Current context and decisions

- Repository: `irigate/irigate-mcp-proxy`, branch `main`.
- Product boundary: loopback-only local MCP broker for developers running multiple AI coding agents; not an enterprise gateway, remote service, identity layer, Kubernetes control plane, or model API proxy.
- Existing source material: `README.md`, `IMPLEMENTATION.md`, `MARKET-RESEARCH.md`, and generated brand assets under `assets/`.
- Existing visual contract: gold `#ffc72c`, amber `#f9a23a`, Georgia serif wordmark, Iris-gate mark, transparent assets.
- Hosting: static GitHub Pages deployment with custom apex domain `irigate.io`.
- Astro configuration: `site: "https://irigate.io"`, static output, no `base` because the custom domain is at the origin root.
- Site location: dedicated `site/` directory so Node dependencies and generated output do not mix with the Python package. The Python `dist/` already lives at the repo root (sdist/build, already gitignored) and `site/dist/` is segregated by directory; the two directories do not collide but will be sibling-named, so `.gitignore` and operator scripts must be explicit about which `dist/` they refer to.
- Content model: page copy and documentation live as Markdown/MDX under `site/src/content/`. Astro components own layout and visual presentation; substantive product text remains editable as content rather than being embedded throughout templates.
- Content sourcing model: hand-derive `site/src/content/docs/*.md` from current `README.md`, `IMPLEMENTATION.md`, and `MARKET-RESEARCH.md` once per content change. Do not parse arbitrary headings out of those root docs at build time — that would create brittle coupling to document structure. The synchronization contract lives in `site/AGENTS.md` and is enforced by the Phase 6 path filters.
- Design direction: technical editorial with complete light and dark palettes—ink surfaces in dark mode, warm paper surfaces in light mode, existing gold/amber accent, serif display headings, neutral sans-serif body, terminal and architecture panels, restrained motion, and no decorative AI gradients.
- Theme contract: expose explicit Light, Dark, and System choices. Default to System, persist an explicit choice locally, and continue following OS changes while System is selected.
- JavaScript policy: static HTML and CSS by default. Allow only small framework-free scripts for the theme preference and concrete interactions such as copying a command.
- Package manager: pnpm with a committed `pnpm-lock.yaml` and pinned package-manager version in `site/package.json`. `@astrojs/check` and `typescript` are devDependencies; pinning them as runtime deps will introduce duplicate `astro` entries in the lockfile.
- Versions observed on 2026-07-11: Astro `7.0.7`, `@astrojs/mdx` `7.0.2`, `@astrojs/sitemap` `3.7.3`. Resolve and lock compatible versions during implementation rather than relying on floating versions.
- Official GitHub Pages workflow versions observed in current Astro guidance: `actions/checkout@v7` (latest `v7.0.0`), `withastro/action@v6`, `actions/deploy-pages@v5` (latest `v5.0.0`), Node 24. GitHub runners force Node 24 for JS actions as of 2026-06-02; the plan pins Node 24 explicitly.
- Pin-to-SHA policy: this plan mixes pinning conventions. Action majors (`@v5`, `@v6`, `@v7`) follow GitHub's official-published major for these maintained actions; third-party packages use semver ranges plus the committed lockfile. Do not introduce a third convention.

## Proposed site structure

```text
GITHUB-PAGES.md
site/
├── AGENTS.md
├── README.md
├── package.json
├── pnpm-lock.yaml
├── astro.config.mjs
├── tsconfig.json
├── public/
│   ├── CNAME
│   ├── favicon.svg
│   ├── logo.svg
│   ├── logo-mark.svg
│   └── og-default.png
├── scripts/
│   └── verify-built-site.mjs
└── src/
    ├── components/
    │   ├── ArchitectureDiagram.astro
    │   ├── BenchmarkEvidence.astro
    │   ├── Callout.astro
    │   ├── CodeBlock.astro
    │   ├── FeatureGrid.astro
    │   ├── Footer.astro
    │   ├── Header.astro
    │   ├── SeoHead.astro
    │   └── ThemeSwitcher.astro
    ├── content/
    │   ├── config.ts
    │   ├── pages/
    │   │   ├── home.mdx
    │   │   └── benchmarks.mdx
    │   └── docs/
    │       ├── index.md
    │       ├── getting-started.md
    │       ├── configuration.md
    │       ├── agent-selection.md
    │       ├── operations.md
    │       ├── safety.md
    │       └── faq.md
    ├── layouts/
    │   ├── BaseLayout.astro
    │   └── DocumentLayout.astro
    ├── pages/
    │   ├── index.astro
    │   ├── benchmarks.astro
    │   ├── llms.txt.ts
    │   ├── robots.txt.ts
    │   └── docs/
    │       └── [...slug].astro
    └── styles/
        ├── global.css
        └── tokens.css
.github/
└── workflows/
    ├── site-check.yml
    └── site-deploy.yml
```

The exact component count may shrink during implementation. Do not create a component that is used only once unless it materially clarifies a large page.

## Page content and acceptance criteria

### `/` — product landing page

Source: `site/src/content/pages/home.mdx` rendered by `site/src/pages/index.astro`.

Sections, in order:

1. Header with Irigate logo, Docs, Benchmarks, GitHub, and Get started.
2. Hero:
   - H1: “Share local MCP servers across your AI coding agents.”
   - One concise definition containing “local MCP broker,” “stdio MCP servers,” and “AI coding agents” naturally.
   - Primary CTA to `/docs/getting-started/`; secondary CTA to GitHub.
   - Terminal/config example using real current commands.
3. Before/after architecture:
   - Before: each agent launches duplicate stdio servers.
   - After: agents use one loopback Streamable HTTP broker; each upstream remains qualified-shared or session-isolated.
4. Evidence strip:
   - Five clients: 80% fewer Context7 instances and 79.0% lower resident memory.
   - Twenty clients: 95% fewer instances and 94.7% lower resident memory.
   - Label evidence as identical-context Context7 measurements.
   - State that throttled calls do not support a latency claim.
5. Three core differentiators: workstation-local consolidation, fail-closed sharing, metadata-only visibility.
6. How it works: configure, start, connect/select.
7. Copyable quick start using `uv tool install`, a minimal profile, and a loopback client URL.
8. Compatibility and boundaries: validated clients, qualified Context7, isolated code-review-graph, explicit non-goals.
9. FAQ preview linking to `/docs/faq/`.
10. Final CTA and footer.

Do not claim universal memory savings, improved latency, enterprise governance, compliance, authentication, remote access, or safe sharing of arbitrary MCP servers.

### `/docs/` — documentation index

Source: `site/src/content/docs/index.md`.

- Brief product definition and task-oriented cards.
- Link to every documentation page.
- Prominent “first local run” path.
- Link to repository implementation contracts for contributors.

### `/docs/getting-started/`

Source: `site/src/content/docs/getting-started.md`.

- Requirements.
- Install from repository checkout.
- Minimal profile.
- Validate with `--check`.
- Start broker.
- Connect one client with an exact `tools=` selection.
- Expected local URL and shutdown behavior.
- Link to configuration and agent-selection pages.

### `/docs/configuration/`

Source: `site/src/content/docs/configuration.md`.

- Broker and upstream field contracts from current implementation.
- Safe credential references via `${ENV_NAME}` without example secrets.
- Reload behavior.
- Qualified sharing versus isolation.
- Links back to relevant source documentation instead of duplicating every field table if duplication would drift.

### `/docs/agent-selection/`

Source: `site/src/content/docs/agent-selection.md`.

- Exact `tools=` selection as the recommended least-privilege path.
- Positive, reverse, and mixed `upstreams=` semantics.
- `agent=` attribution and its non-authentication boundary.
- Reload broadening risk for reverse-only selection.
- Valid and rejected URL examples.

### `/docs/operations/`

Source: `site/src/content/docs/operations.md`.

- `irigate tools`, `call`, `ps`, `qualify`, serving, reload, and shutdown.
- Network/package-start side effects of runtime discovery.
- Metadata-only report boundary.
- Troubleshooting links.

### `/docs/safety/`

Source: `site/src/content/docs/safety.md`.

- Loopback-only boundary and Origin enforcement.
- Isolated by default; qualified sharing only.
- No request-delivered credentials.
- Arguments/results excluded from reports and audit records.
- Explicit list of non-goals.
- Avoid “secure” as an unqualified blanket claim.

### `/benchmarks/`

Source: `site/src/content/pages/benchmarks.mdx`.

- Reproduce the measured 1/5/20-client table from `MARKET-RESEARCH.md`.
- Separate instance/process/RSS evidence from invalid throttled latency evidence.
- Explain identical-context limitation, test harness, and evidence gaps.
- Link to benchmark script and source market-research document.
- Use accessible HTML table markup with a useful small-screen treatment.

### `/docs/faq/`

Source: `site/src/content/docs/faq.md`.

Answer high-intent questions in visible HTML:

- What is an MCP broker?
- Why share local MCP servers?
- Is every MCP server safe to share?
- Does Irigate send data to a cloud service?
- Is Irigate an MCP gateway?
- How is it different from enterprise MCP gateways?
- Which coding agents work with it?
- Does it improve latency?

Add matching `FAQPage` JSON-LD only when every structured answer is also visible on the page.

## SEO, accessibility, and performance contracts

### Metadata

Create a reusable `SeoHead.astro` used by every route:

- Unique `<title>` and meta description for each page.
- Absolute canonical URL derived from `Astro.site` and the route.
- Open Graph and Twitter card metadata.
- Default social image at `https://irigate.io/og-default.png` (1200×630 PNG, site-owned designed cover — not a `build_logo.py` output).
- `SoftwareApplication` JSON-LD on the homepage with truthful fields only: name, description, application category, operating-system scope, URL, source-code URL, and version when reliably available.
- `FAQPage` JSON-LD only on the FAQ route.
- `<link rel="sitemap">` and favicon declarations.
- Concrete JSON-LD route map an implementer can grep against: homepage contains exactly `application/ld+json` with `"@type":"SoftwareApplication"`; FAQ contains exactly `application/ld+json` with `"@type":"FAQPage"`; every other route contains no JSON-LD. Catch the `application/ld+json` literal in `verify-built-site.mjs` and assert the type graph at that location.

Content schemas must require unique title, description, and SEO description fields. Descriptions should be concise and specific; reject missing frontmatter during build.

### Crawlability

- Configure `@astrojs/sitemap` with `site: "https://irigate.io"`.
- Generate `robots.txt` from `Astro.site` so the sitemap URL cannot drift.
- Generate `/llms.txt` at build time from a dedicated Astro endpoint and the validated content collection metadata. Follow the current `llmstxt.org` proposal: one H1, a concise blockquote summary, brief interpretation notes, and H2-delimited lists of absolute links with descriptions.
- Keep `llms.txt` curated rather than copying the complete site or sitemap. Use `Docs`, `Evidence`, `Source`, and `Optional` sections; put secondary material under the spec-defined `Optional` heading.
- Include the product boundaries needed to prevent incorrect answers: Irigate is loopback-only, sharing is explicit and qualified, and current benchmark evidence does not establish a latency improvement.
- Link to canonical public documentation pages and useful repository Markdown sources. Do not invent `.md` mirrors unless the implementation actually publishes and verifies those routes.
- Treat `llms.txt` as an experimental discovery aid, not an access-control mechanism, crawler directive, SEO ranking guarantee, or replacement for `robots.txt` and the sitemap.
- Ensure navigation uses ordinary `<a href>` links and all substantive content is present without JavaScript.
- Add useful internal links between related docs pages.
- Keep one H1 per page and use sequential heading levels.
- Avoid duplicate page titles and duplicate canonical URLs.

### Accessibility

- Semantic landmarks: header, nav, main, article/section, footer.
- Skip-to-content link.
- Keyboard-visible focus state.
- Sufficient WCAG AA contrast for text, controls, focus indicators, code, diagrams, and gold/amber accents in both light and dark palettes.
- The Light/Dark/System control must be keyboard operable, expose its current state and accessible name, work without pointer-specific interactions, and avoid icon-only ambiguity.
- Set `color-scheme` consistently so native controls match the effective palette.
- Informative alt text for architecture imagery; empty alt for decorative shapes.
- Copy buttons must announce success without stealing focus.
- Respect `prefers-reduced-motion`.
- No horizontal page overflow at 320 CSS pixels.

### Performance

- Static output only.
- No front-end framework or hydration for layout/content.
- Implement theme switching with CSS custom properties and a tiny inline script, not a hydrated framework component.
- Inline or bundled critical CSS; no remote font dependency. Prefer a system sans-serif stack plus Georgia for display typography.
- Optimize the default social image separately; normal pages should reuse the existing SVG assets.
- Target local Lighthouse scores of at least 95 for Performance, Accessibility, Best Practices, and SEO on the built homepage. Run Lighthouse manually against `pnpm preview` during Phase 8 post-deployment verification; do NOT add Lighthouse CI to the Phase 6 workflow — score noise does not belong in the correctness gate.

## Implementation phases

## Progress

| Phase | Status | Checkpoint |
| --- | --- | --- |
| Phase 0 — confirm open deployment inputs | Gated | Required before Phases 8 and 10; does not block local implementation. |
| Phase 1 — establish the site boundary and tooling | Done | Committed as `88e67d6`. |
| Phase 2 — implement design tokens and shared layouts | Done | Committed as `9346051`. |
| Phase 3 — implement typed Markdown/MDX content | Done | Committed as `9833c20`. |
| Phase 4 — add SEO assets and generated crawler files | Done | Committed as `5cbe7bd`. |
| Phase 5 — add deterministic built-site verification | Done | Committed as `89664bb`. |
| Phase 6 — add pull-request and push validation workflow | Done | Committed as `b782225`; local `act` requires a Docker daemon. |
| Phase 7 — add GitHub Pages deployment workflow | Done | Committed as `139e79a`; local `act` requires a Docker daemon. |
| Phase 0 — confirm open deployment inputs | Done | Authorized by Raphael Bossek in `GITHUB-PAGES.md`. |
| Phase 9 — add GitHub Pages maintenance guide | Done | Verification passed; commit checkpoint pending. |
| Phase 8 — configure and verify the custom domain | Todo | Starts after the Phase 9 prerequisite commit. |
| Phase 10 — update repository-facing documentation | Todo | Starts after the domain gate and maintenance guide are complete. |

### Phase 0 — confirm open deployment inputs (gate, not a build phase)

The four deployment-input questions below are not blockers for local development or for Phase 1–7, but they MUST be resolved before Phase 8 (custom-domain cutover) and Phase 10 (closeout) can be called complete. This phase produces written answers; it does not produce code.

Inputs:

1. Confirm which GitHub account or organization owns/verifies `irigate.io`.
2. Confirm DNS provider access and whether it supports apex ALIAS/ANAME flattening.
3. Confirm whether `www.irigate.io` should redirect to the apex; recommended: yes.
4. Confirm GitHub Pages is enabled for `irigate/irigate-mcp-proxy` and the repository visibility/plan permits it.

Gate: a written section in `GITHUB-PAGES.md` (Phase 9) records every answer and the operator's name; without those entries, Phase 8 cutover is not permitted.

Re-check the current GitHub Pages DNS guidance (A records, AAAA records, apex flattening options, custom-domain verification) immediately before Phase 8 implementation. Do not rely on values written here.

### Phase 1 — establish the site boundary and tooling

Files:

- Create `site/AGENTS.md` with purpose, ownership, content/claim contracts, design guidance, verification commands, and child index.
- Update root `AGENTS.md` Child DOX Index to include `site/AGENTS.md`.
- Create `site/README.md` with local setup, scripts, content ownership, and deployment notes.
- Create `site/package.json`, `site/pnpm-lock.yaml`, `site/astro.config.mjs`, and `site/tsconfig.json`.
- Create `site/pnpm-workspace.yaml` with an explicit allowlist for required dependency build scripts; pnpm 11 rejects unreviewed install scripts, and Astro requires esbuild's install script.
- Update root `.gitignore` to include `site/node_modules/`, `site/dist/`, `site/.astro/`, and any other confirmed Astro-generated local artifacts. Do not ignore source-owned `*.d.ts` indiscriminately; inspect what Astro generates first. Add only the explicit Astro-artifact paths rather than a blanket `site/*`.

Dependencies:

- `astro`
- `@astrojs/mdx`
- `@astrojs/sitemap`
- `@astrojs/check` (devDependency)
- `typescript` (devDependency)

Scripts:

- `pnpm dev` — start local Astro development server.
- `pnpm build` — produce `site/dist/`.
- `pnpm preview` — serve the built output locally.
- `pnpm astro check` or `pnpm check:types` — Astro/TypeScript validation.
- `pnpm verify` — type check, production build, and built-output assertions.

Verification:

```bash
cd site
corepack enable
pnpm install --frozen-lockfile
pnpm astro check
pnpm build
pnpm preview --host 127.0.0.1
```

Confirm the dev and preview servers bind locally. Do not expose them on a non-loopback interface by default.

### Phase 2 — implement design tokens and shared layouts

Files:

- `site/src/styles/tokens.css`
- `site/src/styles/global.css`
- `site/src/layouts/BaseLayout.astro`
- `site/src/layouts/DocumentLayout.astro`
- shared header, footer, SEO, theme switcher, code, callout, feature, architecture, and evidence components as justified by reuse.

Design tokens should name semantic roles rather than individual sections: background, surface, text, muted text, border, accent, accent-strong, focus, code surface, diagram line, max content width, reading width, spacing scale, radii, and shadow. Define each color role for both light and dark modes; components must consume semantic tokens rather than hard-coded mode-specific colors.

Theme behavior:

- Apply an effective `data-theme="light|dark"` attribute to the root element.
- Store only the user’s preference (`light`, `dark`, or `system`) under a stable, documented local-storage key.
- Run the preference bootstrap in `<head>` before rendering visible content to avoid a flash of the wrong theme.
- Guard local-storage access so denied storage does not break rendering; fall back to System.
- While preference is System, listen to `prefers-color-scheme` changes and update immediately. Explicit Light or Dark must ignore subsequent OS changes.
- Use a three-choice labelled control rather than an ambiguous two-state toggle. Update `aria-pressed` or equivalent selected semantics correctly.
- Keep the site fully readable if JavaScript is disabled by using `prefers-color-scheme` as the CSS fallback; preference persistence and manual switching may require JavaScript.

Verification:

- Render a temporary content page through each layout.
- Check desktop and 320/768/1280-pixel widths.
- Check keyboard navigation, skip link, focus states, light/dark contrast, reduced motion, and print/readability behavior.
- Test first visit in light and dark OS modes, all three manual choices, reload persistence, System-mode response to a live OS change, denied local storage, JavaScript disabled fallback, and absence of a visible wrong-theme flash.

### Phase 3 — implement typed Markdown/MDX content

Files:

- `site/src/content.config.ts` (Astro 7's content-collection entry point)
- Markdown/MDX files listed under “Page content and acceptance criteria.”
- `site/src/pages/docs/[...slug].astro`
- the `site/src/pages/index.astro` and `site/src/pages/benchmarks.astro` route files, each rendering the corresponding MDX entry.

Use Astro build-time content collections with `glob()` loaders and schemas. Use Markdown for prose-heavy documentation; use MDX only when a page needs approved reusable components such as the architecture diagram or evidence table.

Content sourcing rules:

- Hand-derive `site/src/content/docs/*.md` and `site/src/content/pages/*.mdx` from current `README.md`, `IMPLEMENTATION.md`, and `MARKET-RESEARCH.md` once per content change. No build-time parsing of those root docs.
- Do not parse arbitrary headings out of those root files at runtime; that would create a brittle coupling to document structure.
- Add a prominent source link from benchmark and implementation-oriented pages.
- When product behavior or benchmark evidence changes, update the applicable website Markdown in the same change. Record this synchronization contract in `site/AGENTS.md` and the root DOX ownership text.

Verification:

- Every planned route builds.
- Every Markdown/MDX entry passes schema validation.
- No page contains unsupported claims.
- Commands match the current CLI and profiles.
- Internal links resolve in the static output.

### Phase 4 — add SEO assets and generated crawler files

Files:

- Copy generated `assets/logo.svg` and `assets/logo-mark.svg` into `site/public/` without hand-editing their geometry.
- Create `site/public/og-default.png` as a site-owned artifact at 1200×630 PNG. This is a designed social cover, not a brand-asset-generator output — `assets/build_logo.py` produces transparent brand lockups and its contract (`assets/AGENTS.md`) restricts generated imagery to the IRIGATE wordmark and SVG title/description. A social cover typically needs a tagline and background composition that exceed that contract. Either hand-compose it once and commit the PNG, or add a site-specific generator script at `site/scripts/generate-og-image.mjs` that imports the logo SVG and composes it onto a 1200×630 canvas. Do not extend `assets/build_logo.py` for this purpose.
- Add sitemap integration and `site/src/pages/robots.txt.ts`.
- Add `site/src/pages/llms.txt.ts`; produce UTF-8 `text/plain` Markdown with absolute `https://irigate.io` URLs derived from `Astro.site` and descriptions from validated content frontmatter.
- Add JSON-LD through the SEO component.

If `assets/build_logo.py` gains new outputs, update `assets/AGENTS.md` and its verification contract in the same change. The OG social cover (`site/public/og-default.png`) is explicitly NOT a `build_logo.py` output — it is a site-owned artifact.

Verification:

- Inspect the built `<head>` of every route.
- Verify canonical URLs use `https://irigate.io` and contain no repository base path.
- Verify sitemap contains every public route exactly once.
- Verify robots references the generated sitemap URL.
- Verify `/llms.txt` returns `200`, uses a `text/plain; charset=utf-8` content type, conforms to the expected heading/list structure (one `^# .+$` line, then `^## (Docs|Evidence|Source|Optional)$` sections, in that order), contains only valid absolute URLs, and has no duplicate or broken links.
- Verify the guide is concise enough for discovery and does not reproduce credentials, commands containing credentials, payload examples, unsupported marketing claims, or the repository-only `GITHUB-PAGES.md` guide.
- Validate JSON-LD with a parser and, when deployed, Google Rich Results Test where applicable.
- Confirm social image dimensions are exactly 1200×630 and file size is suitable for Open Graph previews.

### Phase 5 — add deterministic built-site verification

Create `site/scripts/verify-built-site.mjs` using Node standard library unless a dependency is clearly justified.

Checks against `site/dist/`:

- Read `site/package.json`'s `packageManager` field and assert the lockfile header (`lockfileVersion` and the `pnpm` line if present) matches the expected format. Catch the most common lockfile-regeneration drift before the GitHub workflow catches it.
- Required routes and files exist.
- Favicon, robots, sitemap, `llms.txt`, and social image exist. Validate `CNAME` exactly when present; Phase 8 makes it required after the custom-domain gate is satisfied.
- Every HTML page has exactly one title, canonical URL, description, and H1.
- No built canonical URL contains `/irigate-mcp-proxy/`.
- No page contains `noindex`.
- Internal root-relative links resolve to built files or known generated endpoints.
- Every absolute URL listed in `llms.txt` is unique, HTTPS, within the approved public-site/repository allowlist, and resolves locally when it targets the built site.
- `llms.txt` has exactly one H1, the required Irigate summary, expected H2 sections, and no reference to `GITHUB-PAGES.md`.
- Images have alt attributes.
- Homepage contains the explicit product boundary and evidence limitation text.
- CNAME content, if retained, is exactly `irigate.io` plus a final newline.
- Every HTML page includes the early theme bootstrap and the Light/Dark/System control; static checks assert the three supported preference values (`light`, `dark`, `system`) and no hard dependency on client-side framework code.
- Every HTML page's JSON-LD content (if any) contains `application/ld+json`; the homepage must contain at least one such block with `"@type":"SoftwareApplication"`, the FAQ page must contain at least one such block with `"@type":"FAQPage"`. Other pages may optionally include `BreadcrumbList` or other valid schema; assert the two required types exist where expected, but do not assert zero JSON-LD on all other pages.

Run the project's preferred Markdown link-check workflow against source Markdown/MDX as a separate check using the `check-md-links` skill; do not treat built HTML link validation as a substitute for source-document validation. Use default file-on-disk resolution — this site uses plain Astro content collections with `glob()` loaders, not Starlight's file-as-directory routing, so the `--starlight` flag is not applicable.

Verification:

```bash
cd site
pnpm verify
```

Expected result: Astro check succeeds, the production build succeeds, and built-site assertions exit 0.

### Phase 6 — add pull-request and push validation workflow

Create `.github/workflows/site-check.yml`.

Triggers:

- `pull_request`
- pushes to non-deployment branches if useful for this repository
- path filters for:
  - `site/**`
  - `assets/**`
  - `AGENTS.md` (root)
  - `README.md`
  - `IMPLEMENTATION.md`
  - `MARKET-RESEARCH.md`
  - `.github/workflows/site-check.yml`
  - `.github/workflows/site-deploy.yml`

Job:

1. Checkout with `actions/checkout@v7`.
2. Enable the package manager version pinned by `packageManager` in `site/package.json` via Corepack.
3. Set up Node 24 with `actions/setup-node@v5`, enabling dependency caching on `site/pnpm-lock.yaml`.
4. Run `pnpm install --frozen-lockfile` from `site/`.
5. Run `pnpm verify`.
6. No Lighthouse CI step. This plan deliberately keeps noisy score-based checks out of the correctness gate.

Do NOT use `withastro/action` in this workflow — that action is for deployment (Phase 7). It builds a Pages artifact and uploads it, which is wrong for a PR check. The check workflow uses plain `setup-node` + `pnpm install` + `pnpm verify`.

Use least-privilege `contents: read`. No secrets are required.

Local workflow testing:

```bash
gh act pull_request -W .github/workflows/site-check.yml
```

If `act` lacks support for an action version or Pages-specific behavior, document the limitation and retain `pnpm verify` as the authoritative local content/build check. Do not weaken the GitHub workflow solely for `act` compatibility.

### Phase 7 — add GitHub Pages deployment workflow

Create `.github/workflows/site-deploy.yml` based on current official Astro guidance.

Triggers:

- push to `main` with path filters for:
  - `site/**`
  - `assets/**`
  - `README.md`
  - `IMPLEMENTATION.md`
  - `MARKET-RESEARCH.md`
  - `.github/workflows/site-deploy.yml`
- `workflow_dispatch`

Permissions:

```yaml
contents: read
pages: write
id-token: write
```

Concurrency:

```yaml
concurrency:
  group: pages
  cancel-in-progress: false
```

Never cancel, always serialize. Pages deploy cancellation is a footgun — a half-written artifact or a stranded deploy can corrupt the environment. A newer push will queue behind the current deploy and run once it finishes.

Build job:

1. Checkout with `actions/checkout@v7`.
2. Run deterministic validation (`pnpm verify`) or configure the official action's `build-cmd` to run it.
3. Use `withastro/action@v6` with `path: site`, Node 24, the pinned pnpm version, and the locked build command. This action builds the site and uploads the Pages artifact in one step — do not add a separate `actions/upload-pages-artifact` step.

Deploy job:

1. Depend on the build job.
2. Use the `github-pages` environment.
3. Deploy with `actions/deploy-pages@v5`.
4. Expose `steps.deployment.outputs.page_url` as the environment URL.

The deployment workflow must run fully on both push and `workflow_dispatch`; do not gate deployment steps to push-only conditions.

Local validation:

- Parse workflow YAML.
- Run `gh act workflow_dispatch -W .github/workflows/site-deploy.yml --job build` when supported.
- Do not expect `act` to perform a real GitHub Pages OIDC deployment.
- A real deployment test requires the workflow committed and available on the remote; `gh workflow run` cannot exercise an unpushed local workflow.

### Phase 8 — configure and verify the custom domain

Re-check the current GitHub Pages DNS guidance (apex A records, AAAA records, ALIAS/ANAME flattening options, custom-domain verification flow) immediately before implementation. Do not rely on values written anywhere else in this plan.

Repository files:

- Add `site/public/CNAME` containing `irigate.io` for explicit ownership and compatibility with Astro’s documented GitHub Pages setup.
- Set Astro `site` to `https://irigate.io`; do not set `base`.

GitHub configuration:

1. Verify domain ownership in the GitHub organization/account before DNS cutover.
2. In repository Settings → Pages, select GitHub Actions as the source.
3. Set the custom domain to `irigate.io`.
4. Enable “Enforce HTTPS” when GitHub makes it available.

DNS configuration for the apex domain:

- Prefer provider-supported `ALIAS`/`ANAME` to the organization’s GitHub Pages domain, or use GitHub’s documented apex A records.
- A literal CNAME at the apex is not portable DNS and should not be the default instruction.
- Optionally configure `www.irigate.io` as a CNAME to the organization’s `github.io` hostname so GitHub can redirect it to the apex domain.
- Do not add wildcard DNS records.

Current GitHub documentation notes that a CNAME file is ignored and not required for custom Actions-based publishing. Keep the file because the user explicitly requested it and Astro still documents it, but treat GitHub repository Pages settings and DNS as authoritative.

Post-deployment verification:

```bash
dig irigate.io +noall +answer -t A
dig www.irigate.io +noall +answer -t CNAME
curl -I https://irigate.io/
curl -fsS https://irigate.io/robots.txt
curl -fsS https://irigate.io/sitemap-index.xml
```

Run a manual Lighthouse against the live `https://irigate.io/` after confirming the deploy is up. Capture scores for Performance, Accessibility, Best Practices, and SEO. The 95-target is for the live site; local preview Lighthouse belongs in the Full verification gate section, not here.

Confirm:

- HTTPS certificate is valid.
- `https://irigate.io/` returns 200.
- GitHub’s default Pages URL redirects or canonicalizes to the custom domain as expected.
- `www` redirects to the chosen canonical apex if configured.
- Canonicals, sitemap, robots, and social image all use `https://irigate.io`.
- No mixed content or repository-base URLs remain.

Phase 0 gate: this phase may not run custom-domain cutover until the four Phase 0 inputs are answered and recorded in `GITHUB-PAGES.md`.

### Phase 9 — add the repository-only GitHub Pages maintenance guide

Create root-level `GITHUB-PAGES.md`. This is an operator and maintainer guide, not public website content. Do not place it under `site/src/content/`, copy it into `site/public/`, add it to Astro content loaders, or link it from the public site navigation or sitemap.

List `GITHUB-PAGES.md` as a root-owned artifact in the root `AGENTS.md` Child DOX Index, sibling to `README.md`, `IMPLEMENTATION.md`, and `MARKET-RESEARCH.md`.

The guide must cover the following areas (let the implementer structure the document; the plan defines scope, not TOC):

1. **Purpose and ownership** — maintains the `irigate.io` deployment for `irigate/irigate-mcp-proxy`; identify control surfaces (`site-check.yml`, `site-deploy.yml`, `site/astro.config.mjs`, `site/public/CNAME`, GitHub Pages settings); the guide itself is not deployed. Record the four Phase 0 inputs with operator names — without these entries the deployment is not authorized.
2. **Prerequisites** — repo admin access, GitHub org/account access for domain verification, DNS provider access, Node 24, Corepack/pnpm, Docker, GitHub CLI, `gh-act`.
3. **First-time GitHub setup** — domain verification, Pages source = GitHub Actions, custom domain, HTTPS.
4. **DNS setup** — apex ALIAS/ANAME or GitHub A/AAAA records, optional `www` CNAME, no wildcards. `site/public/CNAME` is retained intent; Pages settings and DNS are authoritative. Record the values found during the Phase 8 re-check.
5. **Local authoring and production preview** — `corepack enable`, frozen install, `pnpm dev`, `pnpm verify`, `pnpm preview`, minimum routes to inspect.
6. **Local workflow checks** — `gh extension install nektos/gh-act`, run site-check and deploy build job locally; `act` cannot validate OIDC deployment; no secrets needed.
7. **First deployment and manual redeployment** — workflow must be pushed before `gh workflow run`; GitHub UI and CLI paths; verify per-step conclusions.
8. **Post-deployment verification** — DNS (`dig`), HTTPS/redirects (`curl -I`), required pages, robots, sitemap, `llms.txt`, canonical metadata, social image, Pages environment URL, manual Lighthouse run.
9. **Routine maintenance** — version bumps, lockfile refresh, content changes, no credentials to rotate, path-filter coverage; re-check docs before version/DNS changes.
10. **Troubleshooting and rollback** — build failure, skipped deploy step, Pages source misconfiguration, custom-domain conflict, cert pending, DNS propagation, wrong `base`, stale cache, `act`/runner differences. Roll back by reverting and dispatching last known-good `main`.
11. **Decommissioning/security** — remove DNS promptly if Pages is disabled (domain takeover risk); remove custom domain in GitHub's documented order.

Documentation verification:

- Run Markdown link validation over `GITHUB-PAGES.md` using the `check-md-links` skill.
- Confirm every workflow/file/command named in the guide exists after implementation.
- Confirm no generated file under `site/dist/` contains the guide title or a link to `GITHUB-PAGES.md`.
- Review the guide against the final workflow YAML and live GitHub Pages settings; it must document the implemented path, not a generic example.

### Phase 10 — update repository-facing documentation

Files:

- Update root `README.md` with the public website URL and a concise website/docs link.
- Update root `AGENTS.md` Child DOX Index and root-owned artifact description, including `GITHUB-PAGES.md` as the repository-only deployment maintenance guide.
- Link `GITHUB-PAGES.md` from the repository maintenance/development section of `README.md`, not from public website content.
- Update `site/AGENTS.md` with final current ownership and verification commands.
- Update `assets/AGENTS.md` only if the asset generator or owned outputs changed. The OG social cover is site-owned (`site/public/og-default.png`) and does not affect `assets/AGENTS.md`.

DOX closeout:

1. Re-read root and site/asset contracts.
2. Confirm the new `site/` structural boundary is indexed.
3. Confirm the `GITHUB-PAGES.md` root-owned-artifact entry is in the Child DOX Index.
4. Document stable synchronization responsibilities, not implementation history.
5. Remove any plan assumptions contradicted by the final implementation.

## Local developer workflow

First setup:

```bash
cd site
corepack enable
pnpm install --frozen-lockfile
```

Fast authoring loop:

```bash
pnpm dev --host 127.0.0.1
```

Production-equivalent local check:

```bash
pnpm verify
pnpm preview --host 127.0.0.1
```

Open the URL printed by Astro, then test at minimum:

- `/`
- `/docs/`
- `/docs/getting-started/`
- `/docs/agent-selection/`
- `/docs/safety/`
- `/benchmarks/`
- `/docs/faq/`
- `/robots.txt`
- `/llms.txt`
- `/sitemap-index.xml`

Workflow-level local check where supported:

```bash
gh act pull_request -W .github/workflows/site-check.yml
gh act workflow_dispatch -W .github/workflows/site-deploy.yml --job build
```

## Full verification gate

Run before considering implementation complete:

```bash
uv run --frozen pytest -q
uv run --frozen python -m irigate --config profiles/mvp.yaml --check
cd site
corepack enable
pnpm install --frozen-lockfile
pnpm verify
```

Then:

- Run source Markdown/MDX link validation using the `check-md-links` skill with default file-on-disk resolution (not `--starlight` — this site uses plain Astro content collections, not Starlight routing).
- Fetch and inspect the built `/llms.txt`; validate its format and every listed URL.
- Serve `site/dist/` through `pnpm preview` and perform keyboard, mobile-width, no-JavaScript, and reduced-motion checks.
- Run Lighthouse locally (manual) against the preview server. Capture scores; no CI gate is enforced.
- Validate workflow YAML and run the build jobs with `act` where supported.
- Inspect `git diff --check` and `git status --short`.
- After deployment, run the DNS/HTTP checks from Phase 8 and inspect the real GitHub Actions step conclusions; no build or deploy step may be skipped on `workflow_dispatch`.
- Validate `GITHUB-PAGES.md` links and confirm it is absent from `site/dist/`.
- Confirm Phase 0 inputs are recorded in `GITHUB-PAGES.md` before declaring Phase 8 cutover complete.

## Likely files changed

- `.gitignore`
- `AGENTS.md`
- `README.md`
- `GITHUB-PAGES.md`
- `.github/workflows/site-check.yml`
- `.github/workflows/site-deploy.yml`
- `assets/AGENTS.md` and `assets/build_logo.py` only if site-specific logo exports (not the OG social cover) are generated there
- all new files under `site/` listed in the proposed structure

Production Python code and tests should remain unchanged unless implementation uncovers a documentation mismatch that must be corrected at its source.

## Risks and mitigations

- Documentation drift: website content can diverge from root runtime contracts. Mitigate with explicit ownership in `site/AGENTS.md`, workflow path triggers on root docs, source links, and same-change updates for behavior/evidence changes.
- `llms.txt` drift or overclaiming: generate its link inventory from validated metadata, keep boundary text explicit, and assert its structure and approved URLs in built-site verification.
- Unsupported marketing claims: the project’s measured evidence is narrow. Encode evidence limitations in content acceptance checks and review against `MARKET-RESEARCH.md`.
- Apex DNS misunderstanding: `irigate.io` generally cannot use an ordinary portable CNAME. Use ALIAS/ANAME or GitHub A records, reserve CNAME for `www`, and configure the custom domain in GitHub Pages settings.
- CNAME ambiguity with Actions deployment: GitHub currently says the file is ignored/not required for custom workflows while Astro documents adding it. Keep it as requested, but rely on Pages settings and DNS.
- Action/version drift: action majors and Astro packages will evolve. Re-check official Astro and GitHub docs immediately before Phase 1 (Astro/Astro plugins) and Phase 8 (DNS/Domain) and pin the selected package graph in the lockfile.
- `act` parity: local `act` cannot faithfully perform Pages OIDC deployment. Use it for build-job workflow validation; use `pnpm verify` for deterministic local correctness and one real GitHub deployment for the release path.
- Social image scope: the OG cover is a site-owned artifact (`site/public/og-default.png`), not a `build_logo.py` output. Do not extend the brand-asset generator for marketing composition.
- Overengineering: avoid Starlight, a search service, CMS, analytics, React/Vue hydration, or a blog until the content volume and user need justify them. Keep the required theme switcher framework-free and limited to Light/Dark/System preference management.
- Sibling `dist/` confusion: `site/dist/` and the existing Python `dist/` are colocated at the repo root. `.gitignore`, verify scripts, and operator-facing copy must always qualify which `dist/` they mean.

## Open deployment inputs

These do not block implementation of the site or local validation, but they are required before public cutover. They are gated through Phase 0 and recorded in `GITHUB-PAGES.md` before Phase 8:

- Confirm which GitHub account or organization owns/verifies `irigate.io`.
- Confirm DNS provider access and whether it supports apex ALIAS/ANAME flattening.
- Confirm whether `www.irigate.io` should redirect to the apex; recommended: yes.
- Confirm GitHub Pages is enabled for `irigate/irigate-mcp-proxy` and the repository visibility/plan permits it.

## Future work and deferred concerns

These items are explicitly deferred. None blocks the phases above; each is recorded so it is not lost.

- **F1. Lighthouse CI as non-blocking comment** — add a Lighthouse CI job to `site-check.yml` that posts a comment but never fails the workflow, only if score noise becomes manageable.
- **F2. Pin third-party Actions to commit SHA** — if the threat model expands beyond GitHub-maintained actions, switch to 40-char-SHA pinning per the `external-pack-versioning` skill.
- **F3. Starlight evaluation** — if docs grow past ~15 pages or need search/versions/i18n, evaluate Starlight as a drop-in for the hand-rolled layouts.
- **F4. Static search (Pagefind)** — add if users repeatedly need cross-doc search.
- **F5. Multi-locale content** — evaluate Astro i18n routing if non-English audiences become a real signal.
- **F6. Lockfile integrity audit** — extend `verify-built-site.mjs` to walk `pnpm-lock.yaml` and assert every top-level `astro`/`@astrojs/*` resolves to a specific tarball SHA recorded at PR time.
- **F7. Pages environment protection rules** — add required reviewers / branch restrictions on the `github-pages` environment if a second operator joins deployment work.
- **F8. Branded error pages** — add `site/src/pages/404.astro` with design tokens if branded error pages are wanted.
- **F9. URL allowlist as config** — move the hard-coded allowlist in `verify-built-site.mjs` to `site/config/allowlist.json` if the list grows or needs operator review.
- **F10. Subdomain split** — split to `irigate.io` (marketing) and `docs.irigate.io` (docs) if the surfaces diverge enough.

## Completion criteria

The task is complete only when:

- Phase 0 inputs are recorded in `GITHUB-PAGES.md` with an operator name.
- All planned routes are rendered from Markdown/MDX-backed content and pass schema validation.
- The production build and deterministic local verification pass from a clean checkout.
- The built site can be previewed locally with the documented command.
- Light, Dark, and System modes work locally and in the production build, remain accessible, persist correctly, and avoid wrong-theme flashing.
- Pull-request validation and Pages deployment workflows exist and their build jobs pass.
- A manual remote deployment runs every build/deploy step successfully.
- `https://irigate.io` serves the site over HTTPS with correct canonical, sitemap, robots, and social metadata.
- `https://irigate.io/llms.txt` serves a concise, valid, current project guide with verified links and explicit product/evidence boundaries.
- `GITHUB-PAGES.md` accurately documents setup, local testing, deployment, DNS, maintenance, troubleshooting, rollback, and decommissioning, and is not present in the deployed output.
- Published claims remain within current implementation and benchmark evidence.
- Root and site DOX contracts accurately describe the new structure and responsibilities.

# GitHub Pages Maintenance

This repository-only guide maintains the `https://irigate.io` GitHub Pages deployment for `irigate/irigate-mcp-proxy`. It is not public website content: do not move it under `site/src/content/`, copy it into `site/public/`, add it to Astro loaders, or link it from website navigation, sitemap, robots, or `llms.txt`.

## Phase 0 Authorization Gate

Cutover is authorized by the resolved rows below. Recheck every operational fact at execution time; stop if access, repository plan, domain verification, or DNS state differs from this record.

| Input | Observed on 2026-07-11 | Required before Phase 8 cutover | Operator |
| --- | --- | --- | --- |
| GitHub domain verification owner | Organization `irigate` owns and will verify `irigate.io`. | Verify the domain in the `irigate` organization before adding the custom domain. | Raphael Bossek — approved 2026-07-11 |
| DNS provider and apex support | AWS Route 53 apex ALIAS is active. Recursive and all four authoritative nameservers return GitHub Pages A records `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, and `185.199.111.153`. No AAAA records are configured. | Retain the apex ALIAS and GitHub verification TXT record; recheck before Pages setup. | Raphael Bossek — configured and verified 2026-07-11 |
| `www.irigate.io` redirect | `www.irigate.io` CNAME to `irigate.github.io` is active on recursive and all authoritative nameservers. | Retain the CNAME; GitHub Pages performs the redirect to the configured apex after Pages setup. | Raphael Bossek — configured and verified 2026-07-11 |
| Pages availability | Repository visibility is private. GitHub Pages API returned HTTP 404 before setup. Private-repository Pages is permitted and should be enabled. | Enable Pages with GitHub Actions as the source, then set `irigate.io` as the custom domain. | Raphael Bossek — approved 2026-07-11 |

## Control Surfaces

- [`.github/workflows/site-check.yml`](.github/workflows/site-check.yml) runs `pnpm verify` for pull requests and non-`main` pushes that touch site, asset, root product docs, or site workflow files.
- [`.github/workflows/site-deploy.yml`](.github/workflows/site-deploy.yml) builds on `main` pushes and `workflow_dispatch`, uploads `site/` with `withastro/action@v6`, and deploys with `actions/deploy-pages@v5`.
- [`site/astro.config.mjs`](site/astro.config.mjs) sets `site: "https://irigate.io"`, static output, and loopback dev/preview hosts. Do not add a repository `base`.
- [`site/package.json`](site/package.json) requires Node 24, pins `pnpm@11.8.0`, and defines `pnpm verify` as type check, production build, and built-output assertions.
- [`site/scripts/verify-built-site.mjs`](site/scripts/verify-built-site.mjs) validates required routes, metadata, generated crawler files, image dimensions, no repository-base URLs, and that `llms.txt` does not reference this guide.
- GitHub repository Settings -> Pages is authoritative for Pages source, custom domain, and HTTPS enforcement.
- `site/public/CNAME` contains exactly `irigate.io\n` and records repository intent. GitHub documents that Actions-based Pages publishing ignores this file; Pages settings and DNS remain authoritative.

## Prerequisites

- Repository admin access for `irigate/irigate-mcp-proxy`.
- GitHub organization/account access able to verify `irigate.io`.
- DNS provider access to the Route 53 hosted zone.
- Node 24 and Corepack.
- `pnpm` activated from the pinned `packageManager` value.
- GitHub CLI `gh`.
- `gh-act` extension from `nektos/gh-act`.
- Docker daemon for local `act` runs. On 2026-07-11 this checkout is blocked because no Docker socket is available; that does not validate the OIDC deployment path.

## First-Time GitHub Setup

1. Resolve every Phase 0 authorization row with a named human operator.
2. Verify `irigate.io` in the owning GitHub organization/account before DNS cutover. For the organization owner flow, use GitHub organization Settings -> Pages -> Add a domain, add GitHub's `_github-pages-challenge-ORGANIZATION.irigate.io` TXT record in DNS, confirm it with `dig`, then click Verify. Keep the TXT record after verification.
3. In repository Settings -> Pages, set Source to GitHub Actions.
4. Set the custom domain to `irigate.io`.
5. Enable Enforce HTTPS when GitHub makes it available.

GitHub's current Pages docs, rechecked on 2026-07-11, are the source of truth for the custom-domain flow:

- [Managing a custom domain for your GitHub Pages site](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)
- [Verifying your custom domain for GitHub Pages](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages)
- [Securing your GitHub Pages site with HTTPS](https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https)
- [Troubleshooting custom domains and GitHub Pages](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/troubleshooting-custom-domains-and-github-pages)

## DNS Setup

Recheck GitHub's DNS records immediately before Phase 8 execution. Values below were rechecked against official GitHub docs on 2026-07-11 and must not be treated as permanent.

The active apex configuration is a Route 53 ALIAS to `irigate.github.io`. The resulting authoritative A records are:

- GitHub Pages A records:
  - `185.199.108.153`
  - `185.199.109.153`
  - `185.199.110.153`
  - `185.199.111.153`
- Optional IPv6 support is not configured. If added later, use all GitHub Pages AAAA records alongside the apex ALIAS/A results:
  - `2606:50c0:8000::153`
  - `2606:50c0:8001::153`
  - `2606:50c0:8002::153`
  - `2606:50c0:8003::153`

`www.irigate.io` has an active CNAME pointing directly to `irigate.github.io`, without the repository name. Do not add wildcard DNS records. Remove conflicting default, extra apex, or stray subdomain records before certificate provisioning.

`site/public/CNAME` records repository intent only. GitHub Pages settings and DNS remain authoritative.

## Local Authoring And Preview

```bash
cd site
corepack enable
corepack prepare "$(node -p "require('./package.json').packageManager")" --activate
pnpm install --frozen-lockfile
pnpm dev
pnpm verify
pnpm preview
```

Inspect at minimum:

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

## Local Workflow Checks

Install the local runner extension if needed:

```bash
gh extension install nektos/gh-act
```

Run the workflow jobs locally where Docker is available:

```bash
gh act pull_request -W .github/workflows/site-check.yml
gh act workflow_dispatch -W .github/workflows/site-deploy.yml --job build
```

Local `act` runs do not validate GitHub Pages OIDC deployment, Pages environment protection, GitHub-hosted runner behavior, or `actions/deploy-pages@v5`. No secrets are needed for the local build checks.

## Deployment

The deploy workflow must exist on the pushed branch before manual dispatch can work.

First deployment:

1. Resolve the Phase 0 authorization gate.
2. Push the workflow and site changes to `main`.
3. Confirm `.github/workflows/site-deploy.yml` runs the `build` job and then the `deploy` job.
4. Inspect each real GitHub Actions step conclusion; no build or deploy step may be skipped.
5. Confirm the Pages environment URL is the deployed site URL.

Manual redeployment:

```bash
gh workflow run "Deploy site" --repo irigate/irigate-mcp-proxy
gh run list --workflow "Deploy site" --repo irigate/irigate-mcp-proxy --limit 5
gh run view RUN_ID --repo irigate/irigate-mcp-proxy --log
```

The GitHub UI path is Actions -> Deploy site -> Run workflow.

## Post-Deployment Verification

Run DNS checks:

```bash
dig irigate.io +noall +answer -t A
dig irigate.io +noall +answer -t AAAA
dig www.irigate.io +noall +answer -t CNAME
dig _github-pages-challenge-irigate.irigate.io +nostats +nocomments +nocmd TXT
```

Run HTTP checks:

```bash
curl -I https://irigate.io/
curl -I http://irigate.io/
curl -I https://www.irigate.io/
curl -fsS https://irigate.io/robots.txt
curl -fsS https://irigate.io/sitemap-index.xml
curl -fsS https://irigate.io/llms.txt
curl -I https://irigate.io/og-default.png
```

Confirm:

- HTTPS certificate is valid and Enforce HTTPS is enabled.
- `https://irigate.io/` returns 200.
- HTTP redirects to HTTPS.
- `www` redirects to apex if configured.
- The default GitHub Pages URL redirects or canonicalizes to `https://irigate.io`.
- Canonical links, sitemap URLs, robots sitemap, and social image URLs use `https://irigate.io`.
- Required pages render: `/`, `/docs/`, `/docs/getting-started/`, `/docs/agent-selection/`, `/docs/safety/`, `/benchmarks/`, `/docs/faq/`.
- `llms.txt` contains the expected concise public index and no `GITHUB-PAGES.md` reference.
- No mixed content or `/irigate-mcp-proxy/` repository-base URLs remain.
- Manual Lighthouse against the live homepage records Performance, Accessibility, Best Practices, and SEO scores; target each score at 95 or higher.

## Routine Maintenance

- Before action, Astro, pnpm, Node, DNS, or Pages changes, recheck the official GitHub and Astro docs.
- For dependency maintenance, update `site/package.json` and `site/pnpm-lock.yaml` together, then run `pnpm verify`.
- For content changes, keep root source docs and `site/src/content/` synchronized by hand in the same change.
- Keep workflow path filters covering website files, assets, root product docs, and workflow files.
- Do not rotate website credentials; this static site has no deployment secrets. The workflow uses GitHub-provided `pages: write` and `id-token: write` permissions.
- Keep the repository free of DNS credentials, tokens, API keys, and copied Pages settings exports.

## Troubleshooting And Rollback

- Build failure: reproduce with `cd site && pnpm verify`; fix source, lockfile, or built-output assertions before rerunning.
- Skipped deploy step: inspect workflow event, branch, path filters, job dependencies, and environment state. `workflow_dispatch` must run both build and deploy jobs.
- Pages source misconfiguration: repository Settings -> Pages must use GitHub Actions.
- Custom-domain conflict: verify the domain in the owning GitHub organization/account, then retry adding `irigate.io`.
- Certificate pending: verify DNS, remove extra conflicting records, wait for propagation, and if needed remove/re-add the custom domain in Pages settings to restart provisioning.
- DNS propagation: allow up to 24 hours and compare authoritative Route 53 answers before recursive resolver answers.
- Wrong `base`: keep Astro without `base`; repository-base URLs must fail `site/scripts/verify-built-site.mjs`.
- Stale browser cache: retest with `curl`, a clean profile, or cache disabled.
- `act`/runner differences: local `act` validates only build mechanics; trust real GitHub Actions for Pages upload/deploy and OIDC behavior.

Rollback is a repository operation: revert the bad `main` change or restore the last known-good commit, push it, dispatch `Deploy site`, and verify the real workflow and live site. Do not roll back by changing DNS unless decommissioning or an incident response requires it.

## Decommissioning And Security

If GitHub Pages is disabled, remove or change DNS records promptly to prevent domain takeover risk. Remove the custom domain in GitHub Pages settings before deleting the repository, disabling Pages, downgrading the plan, or repointing DNS away from GitHub Pages. Keep domain verification TXT records unless the owning organization/account intentionally relinquishes the domain.

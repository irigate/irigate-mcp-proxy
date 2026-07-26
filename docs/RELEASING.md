# Release Irigate

Irigate releases are immutable, tag-driven deployments. Pushing a matching `vX.Y.Z` tag runs `.github/workflows/publish.yml`, which tests and builds the package, publishes it to production PyPI through OpenID Connect Trusted Publishing, then creates the GitHub Release with the same wheel and source archive.

Branch pushes, pull requests, and manual workflow dispatches do not publish. No long-lived PyPI token belongs in GitHub Secrets.

## Release contract

A release proceeds only when all of these are true:

1. The tag is `v` plus the exact `src/irigate/__init__.py` `__version__` value.
2. `pyproject.toml` declares the same package version.
3. `docs/releases/<tag>.md` exists in the tagged commit.
4. The test suite, package build, and `twine check` pass.
5. The publish job is admitted to the `pypi` GitHub environment.
6. PyPI accepts the OIDC identity for `irigate/irigate-mcp-proxy`, `publish.yml`, and the `pypi` environment.

The GitHub Release is created only after PyPI publishing succeeds. Its body is the versioned release-notes file, and its assets are the exact distributions passed between jobs through the GitHub Actions artifact.

## One-time production setup

### 1. Secure the PyPI maintainer account

Create or use a PyPI account with a verified email address. Enable two-factor authentication and store recovery codes outside the repository. The account configures project ownership and Trusted Publishing; the release workflow does not use it directly.

### 2. Create the GitHub environment

In **GitHub → irigate/irigate-mcp-proxy → Settings → Environments**, create an environment named `pypi`.

Configure **Deployment branches and tags** to allow selected tags only, with tag pattern `v*`. Add a maintainer approval gate when the repository plan supports required reviewers. Verify the environment before the first release:

```sh
gh api repos/irigate/irigate-mcp-proxy/environments/pypi \
  --jq '{name, deployment_branch_policy, protection_rules}'
gh api repos/irigate/irigate-mcp-proxy/environments/pypi/deployment-branch-policies \
  --jq '.branch_policies[] | {name, type}'
```

### 3. Confirm the pending PyPI Trusted Publisher

Sign in at <https://pypi.org/manage/account/publishing/> and confirm the pending GitHub publisher uses these exact values:

| Field | Value |
| --- | --- |
| PyPI project name | `irigate` |
| GitHub owner | `irigate` |
| Repository name | `irigate-mcp-proxy` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

A pending publisher is not represented by PyPI's public project API and does not reserve the name. Push the first release promptly after registration. The first successful upload creates the public project and converts the pending publisher into a normal project publisher.

Do not add `PYPI_TOKEN`, `TWINE_PASSWORD`, or equivalent repository secrets. The publish job has job-scoped `id-token: write` permission and exchanges its GitHub OIDC identity for a short-lived PyPI upload credential.

### 4. Confirm the publisher and public-project state

Before the first release, recheck the pending publisher in the PyPI account UI. A `404` from the public project API is expected until the first successful upload and does not show whether the pending publisher exists. Any existing public project response is a stop condition until ownership is established.

```sh
python3 - <<'PY'
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen("https://pypi.org/pypi/irigate/json"):
        raise SystemExit("PyPI project already exists; establish ownership before tagging")
except urllib.error.HTTPError as error:
    if error.code != 404:
        raise
    print("public PyPI project is not created; confirm the pending publisher in the PyPI UI")
PY
```

## Prepare a release

### 1. Start from current `main`

```sh
git switch main
git pull --ff-only origin main
git status --short
```

The working tree must be clean before release preparation.

### 2. Select and apply the version

Use semantic versioning. Increment both declarations to the same value:

- `__version__` in `src/irigate/__init__.py`
- `[project].version` in `pyproject.toml`

Never reuse a version that reached PyPI or TestPyPI; uploaded filenames are immutable. Check both indexes when uncertain:

```sh
python3 - <<'PY'
import json
import urllib.error
import urllib.request

for base in ("https://pypi.org", "https://test.pypi.org"):
    url = f"{base}/pypi/irigate/json"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print(base, "not published")
            continue
        raise
    print(base, sorted(data["releases"]))
PY
```

### 3. Write release notes

Copy `docs/releases/TEMPLATE.md` to `docs/releases/vX.Y.Z.md`. Replace every placeholder and remove empty sections. Write for operators rather than reproducing the commit log. Cover:

- user-visible highlights and behavior changes;
- additions, fixes, security, and reliability changes;
- installation or upgrade commands, required Python versions, and migrations;
- compatibility boundaries, deprecations, and known limitations;
- practical post-install verification.

The filename is a release gate and must exactly match the proposed tag.

### 4. Run full release verification

```sh
rm -rf build dist irigate.egg-info
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen irigate --help
uv run --frozen irigate --config profiles/mvp.yaml --check
uv run --frozen irigate --config profiles/benchmark-heavy.yaml --check
uv build
uv run --frozen python -m twine check dist/*
```

Confirm the built metadata and filenames use the intended version:

```sh
VERSION=$(uv run --frozen python -c 'from irigate import __version__; print(__version__)')
uv run --frozen python - <<PY
from pathlib import Path
from zipfile import ZipFile

version = "$VERSION"
wheel = next(Path("dist").glob(f"irigate-{version}-*.whl"))
with ZipFile(wheel) as archive:
    metadata = archive.read(f"irigate-{version}.dist-info/METADATA").decode()
for line in metadata.splitlines():
    if line.startswith(("Name:", "Version:", "Requires-Python:")):
        print(line)
PY
```

### 5. Review and commit release preparation

```sh
git diff --check
git diff --stat
git diff
git add README.md DEVELOPMENT.md CHANGELOG.md pyproject.toml uv.lock \
  src/irigate/__init__.py docs/ .github/workflows/publish.yml AGENTS.md
# Stage the synchronized website commit separately inside site/ first.
git commit -m "chore(release): prepare X.Y.Z"
```

Stage only intentional changes; do not amend unrelated work into a release commit.

## Publish the release

### 1. Create and verify the tag

Use a signed annotated tag when a signing key is configured. Otherwise use an annotated tag; do not use a lightweight release tag.

```sh
VERSION=$(uv run --frozen python -c 'from irigate import __version__; print(__version__)')
git tag -s "v$VERSION" -m "Irigate $VERSION"
git show --no-patch "v$VERSION"
```

If signed tags are unavailable:

```sh
git tag -a "v$VERSION" -m "Irigate $VERSION"
```

### 2. Push the commit and tag atomically

```sh
git push --atomic origin main "v$VERSION"
```

Never move or recreate a tag after PyPI accepts that version. Correct mistakes with a new patch release.

### 3. Monitor the workflow

```sh
gh run list --workflow publish.yml --limit 5
gh run view RUN_ID --json status,conclusion,jobs \
  --jq '{status, conclusion, jobs: [.jobs[] | {name, status, conclusion}]}'
```

Expected order:

1. `Test and build distributions`
2. `Publish to PyPI`
3. `Create GitHub Release`

If the environment requires approval, approve only after confirming the tag, commit, version, and release notes.

## Verify the published release

Do not treat a green workflow alone as sufficient. Check PyPI, GitHub, and a fresh installation:

```sh
VERSION=$(uv run --frozen python -c 'from irigate import __version__; print(__version__)')
gh release view "v$VERSION" --json tagName,name,url,assets \
  --jq '{tagName, name, url, assets: [.assets[].name]}'
python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("https://pypi.org/pypi/irigate/json") as response:
    data = json.load(response)
print(data["info"]["version"])
print(sorted(file["filename"] for file in data["urls"]))
PY
TMPDIR=$(mktemp -d)
uv venv --python 3.11 "$TMPDIR/venv"
uv pip install --python "$TMPDIR/venv/bin/python" \
  --default-index https://pypi.org/simple "irigate==$VERSION"
"$TMPDIR/venv/bin/irigate" --version
"$TMPDIR/venv/bin/irigate" --help >/dev/null
rm -rf "$TMPDIR"
```

The GitHub Release must contain both `irigate-X.Y.Z-py3-none-any.whl` and `irigate-X.Y.Z.tar.gz`.

## Failure recovery

### Failure before PyPI publishing

Fix the release commit. Increment the version if the failed version reached any package index, create a new tag, and push again. A tag/version mismatch or missing notes file fails before publication.

If the OIDC exchange fails, compare all five identity fields exactly: package, owner, repository, workflow filename, and environment. Confirm that the publish job has `id-token: write` and was admitted to the `pypi` environment. Do not work around a configuration error by adding a long-lived API token.

### PyPI succeeded but GitHub Release creation failed

Use **Re-run failed jobs** on the existing workflow run. Do not rerun all jobs because PyPI rejects duplicate immutable filenames. The failed release job can reuse the successful build artifact while it remains available.

If the artifact expired, download the wheel and source archive from PyPI, verify their hashes against PyPI, then create the release manually with the already-tagged notes:

```sh
gh release create "v$VERSION" dist/* \
  --verify-tag \
  --title "Irigate $VERSION" \
  --notes-file "docs/releases/v$VERSION.md"
```

### Bad release after publishing

Published files cannot be replaced. Prefer a fixed patch release. For a severe security or data-loss defect, yank the affected version in PyPI's project management UI and explain the reason in both the old and replacement GitHub Releases. Yanking discourages new installs but does not delete the release or repair existing installations.

## Optional TestPyPI validation

TestPyPI is separate from production PyPI and has separate accounts, projects, and Trusted Publishers. Use it only for pipeline changes that need an external upload test. Configure a dedicated `testpypi` environment and publisher; never point the production `pypi` job at TestPyPI.

A TestPyPI version cannot be overwritten. Use a new development or release-candidate version and validate installation with TestPyPI as the package index. Do not add TestPyPI as an extra index for general dependency resolution.

## Publisher changes and teardown

Trusted Publishers are scoped to the repository, workflow filename, and environment. Renaming `publish.yml`, moving the repository, changing its owner, or renaming the environment requires updating the publisher on PyPI before the next tag.

To revoke publishing access, remove the Trusted Publisher from PyPI and delete or restrict the GitHub `pypi` environment. There is no API token to rotate. Keep at least two trusted PyPI project owners when practical so account recovery does not depend on one person.

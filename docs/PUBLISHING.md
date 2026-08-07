# Publishing to PyPI

The package publishes to PyPI as **`drift-detector-scan`** (the plain `drift-detector` was blocked by
PyPI's anti-typosquatting check; the name matches the GHCR image). A developer runs it with **no
clone** — the console command is `drift-scan`:

```
uvx --from drift-detector-scan drift-scan run --root .
pipx install drift-detector-scan     # then: drift-scan run --root .
```

Releases are automated by `.github/workflows/publish.yml`, triggered on a `v*` tag. Auth is **PyPI
Trusted Publishing (OIDC)** — no API token is stored in GitHub. You configure the trust link on
PyPI once.

## One-time setup (before the first release)

Because the project does not exist on PyPI yet, add a **pending publisher**:

1. Sign in at <https://pypi.org> and go to **Your projects → Publishing** (or
   <https://pypi.org/manage/account/publishing/>).
2. Under **Add a new pending publisher**, fill in:
   - **PyPI project name**: `drift-detector-scan`
   - **Owner**: `TOPSinfo`
   - **Repository name**: `drift-detector`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`   ← must match `environment: pypi` in the workflow
3. Save. (No token is generated — trust is established by the GitHub OIDC identity of that exact
   workflow in that exact repo/environment.)

After the first successful publish the pending publisher becomes a normal publisher automatically.

## Cutting a release

1. Bump the version in `pyproject.toml` (`[project].version`).
2. Commit it to `master` and let CI go green.
3. Tag and push — the tag must match the pyproject version:
   ```
   git tag v1.0.0 && git push origin v1.0.0
   ```
4. `publish.yml` runs the tests, verifies the tag matches the pyproject version, builds the sdist +
   wheel, and uploads to PyPI with build attestations. Watch it under the repo's **Actions** tab.

## Notes

- The tag/version guard means a mismatched tag fails loudly instead of shipping a wrong-versioned
  wheel.
- The scan engine ships as the pinned `ast-grep-cli==0.44.1` dependency (same version
  `bin/drift-scan` fetches), so an install is self-contained.
- `container.yml` (the GHCR image) also fires on `v*` tags — one tag ships both the PyPI package and
  the container. Keep the two version stories aligned.
- To test the machinery without touching production PyPI, add a TestPyPI pending publisher and a
  `repository-url: https://test.pypi.org/legacy/` step on a throwaway tag first.

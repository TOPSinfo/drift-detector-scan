# The scan container

Drift Detector ships in **two forms** of the same `agent/` code:

| | The plugin | **The container** (this doc) |
|---|---|---|
| Who runs it | a developer, in Claude Code | **GitLab CI**, headless |
| Contains | code + promptfiles (AI-assisted) | code + the ast-grep engine — **no AI** |
| Used for | Learn sessions + ad-hoc scans | the scheduled deterministic **Scan** |

The container is the **Scan** loop: pull it, run `drift run | verify | deliver`, done. It
holds only `agent/` and a pinned `ast-grep` binary — no `commands/` promptfiles and no LLM
client, so "no AI in CI" is a property you can verify by inspecting the image, not a promise.

## Determinism

Two runs must use byte-identical bits (CLAUDE.md principle 3):

- The engine is **version-pinned and sha256-verified** at build time, with **no fall-back to
  latest** — a mismatch or a failed fetch fails the build. The pin is kept identical to
  `bin/drift-scan`'s by `tests/test_container.py` (a version drift fails the test suite).
- The built image is **pinned by digest** in the consumer's CI (below), so every scheduled
  run pulls the exact same image.

Bumping the engine is a deliberate act: change `AST_GREP_VERSION` + `AST_GREP_SHA256` in the
`Dockerfile` and `DRIFT_AST_GREP_VERSION` in `bin/drift-scan` together, **after re-verifying
the ruleset**.

## Build

```bash
docker build -t drift-detector-scan .
```

The `.github/workflows/container.yml` action builds and pushes to
`ghcr.io/topsinfo/drift-detector-scan` on every `v*` tag, tagging by version and by commit
sha. Make the GHCR package **public** once (repo → Packages → settings) so GitLab CI pulls it
with no cross-vendor secret.

## Run

The entrypoint is the `drift` CLI, so a subcommand is all you pass:

```bash
# scan a local checkout (offline for the ast-grep pass; audit reaches OSV/endoflife)
docker run --rm \
  -v "$PWD":/repo:ro -v "$PWD/.drift":/state \
  drift-detector-scan \
  run --root /repo --state /state --now "$(date +%F)"

docker run --rm -v "$PWD/.drift":/state drift-detector-scan verify --state /state
```

Exit codes (the CI contract): `0` clean · `2` error · `3` findings/gate · `4` couldn't
verify (nothing scanned, or a source unreachable — "couldn't check ≠ clean").

## In GitLab CI (illustrative — the full `drift-ops` bootstrap is a separate step)

The container is meant to run from the dedicated `drift-ops` persistence repo, which holds
the fleet config, the catalog overlay, and the committed-back state. A minimal shape:

```yaml
# .gitlab-ci.yml in drift-ops — pin by DIGEST, not a moving tag
scan:
  image: ghcr.io/topsinfo/drift-detector-scan@sha256:<digest>
  variables:
    GITLAB_TOKEN: $DRIFT_READ_TOKEN        # clone + group expansion; masked CI variable
    DRIFT_CATALOG_DIR: catalog             # the writable overlay in the drift-ops checkout
  script:
    - drift run --root "$FLEET_GROUP_URL" --state state --now "$(date +%F)" --pull
    - drift verify --state state           # exit 4 fails the pipeline; exit 3 does NOT
```

`--pull` needs `git` (baked in) and a read token (`GITLAB_TOKEN`/`DRIFT_GIT_TOKEN`, read at
run time, never stored). `drift deliver` (the two issue streams) and committing state back to
`drift-ops` are the next build steps.

## The catalog overlay — how the container learns

The catalogs inside the image are read-only, so a scan reads
**`package baseline + overlay`**: point `DRIFT_CATALOG_DIR` at a directory (in production, the
`catalog/` dir of the `drift-ops` checkout) holding any of `vendors.local.yaml`,
`idioms.local.yaml`, `sunsets.local.yaml`, `attestations.local.yaml`. Each is a YAML list
layered on top of the package file, baseline first (deterministic). Unset the env var and you
get exactly the baseline.

This is how the Learn loop's output reaches the next scan without an image rebuild: an
`drift absorb` run (with `DRIFT_CATALOG_DIR` set) writes verified entries **into the overlay**,
they land in `drift-ops` as a reviewed diff, and the next scheduled `drift run` reads them.
Proven end to end: an overlay `sunsets.local.yaml` adding one Amazon `/sellers/v1` retirement
turns up as a new finding at `src/Api/SellersApi.php:19`, no package edit and no rebuild.

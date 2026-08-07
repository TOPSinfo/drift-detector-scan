# CLAUDE.md — working in Drift Detector

A deterministic, zero-LLM-token scanner that finds dying third-party API integrations —
deprecated packages (CVE/EOL) and **retired vendor APIs** (sunsets) — down to `file:line`,
and says plainly where it is blind. Claude only orchestrates; the heavy work is Python +
the ast-grep static binary.

## The pipeline

```
scan (offline, deterministic)         audit (network)                render
  ast-grep + manifest parse   ──▶   OSV.dev · endoflife.date  ──▶   drift.json  (canonical, schema'd)
  = inventory.json                   + vendor-sunset catalog          ├─ drift.md      (primary view)
                                     = audit.json                     ├─ dashboard.html (viewer)
                                                                      └─ Claude Artifact (in-chat)
```

`drift.json` is the **one contract** (`docs/schema/drift-v1.schema.json`); every other
surface is a *verified projection* of it. `drift-scan verify` re-parses `drift.md` and the
HTML and fails if they disagree with `drift.json`. **A green `verify` is the only claim you
may make that the report is correct** — never "it looks right" (you cannot see rendered
HTML; that has shipped bugs).

## Non-negotiable principles

These are what make the tool trustworthy. Breaking one is a defect even if tests pass.

1. **"Cannot see" ≠ "clean".** A scan that reads nothing (no repo, an unreadable language,
   an unreachable source) must say so and exit non-zero — never a green checkmark. Verdicts
   are KNOWN/UNKNOWN (per repo) and CURRENT/STALE/UNAUDITED (per vendor); "0 findings" for
   an UNAUDITED vendor is *not* evidence of health.
2. **Never invent a date.** Every vendor retirement carries a `source:` URL that was fetched
   *that session*. Undated deprecations say so (`status: deprecated-no-date`). The
   `absorb` gate (`agent/absorb.py`) enforces this — a date with no source is refused. This
   project has been burned by plausible-but-wrong dates; the gate is why.
3. **Deterministic, zero tokens in the scan path.** Same inputs → byte-identical output.
   No `Date.now()`/wall-clock in logic (`now` is passed in). The ast-grep engine is
   **pinned** (`bin/drift-scan`, `AST_GREP_VERSION`) so two machines get the same scanner.
4. **The catalog is data, reviewed.** Vendors/sunsets/idioms/attestations are YAML with
   load-bearing comments (each date's provenance). New entries enter ONLY through staging +
   `drift-scan absorb`, never a direct edit that skips the gate.
5. **Prove a guard against its bug.** A verify invariant or regression test must be shown to
   FAIL on the bug it targets, not merely written. Reproduce first, then fix.

## Working in the repo

- **Tests:** `.venv/bin/python -m pytest -q` (505+, ~12s, no network — I/O is injected).
  `jsonschema` is test-only; runtime is **stdlib + PyYAML** only.
- **Run it:** `./bin/drift-scan run --root <path|url> --state <dir> --now $(date +%F)` then
  `./bin/drift-scan verify --state <dir>`. `plan` previews without scanning;
  `catalog-check` re-checks live vendor sources against the catalog.
- **Layout:** `agent/` runtime · `agent/lib/` the pieces · `bin/drift-scan` the runner ·
  `docs/drift-absorb.md` the catalog-intake doctrine · catalogs are the `*.yaml` under
  `agent/`.

## Adding a vendor

Detection (host in `agent/vendors.yaml`, version format in `classify_url.py`) → catalog its
retirements (`agent/vendor_sunsets.yaml`, path/operation/domain/version-scoped, each
sourced) → attest it (`agent/catalog_attestations.yaml`, with the date you fetched the
page) → wire freshness (`agent/lib/catalog_sources.py`) if the vendor has a machine-readable
source. Computed-lifecycle vendors (Shopify) live in `agent/lib/version_lifecycle.py`. Each
mechanism was chosen to fit that vendor's real source shape — don't force one pattern.

## The Rust port (banked — do NOT start without a trigger)

A rewrite to Rust is the verified end state, not current work. Rust is the *only* language
that links ast-grep natively (`ast_grep_config::from_yaml_string` → `RuleCollection` →
`CombinedScan`, PHP + all 8 languages built in, the same crates the CLI uses) — Go has no
binding (it would shell out, like Python does now) and the Node/napi route puts PHP on a
0.0.x grammar. But the crate API is **officially unstable**; a port pins `ast-grep-* =
"=<version>"` exactly (mirroring `DRIFT_AST_GREP_VERSION` in `bin/drift-scan`) and treats
bumps as ruleset-re-verification events.

**Do not rewrite until a trigger fires** (revisit quarterly): (1) a client needs a single
no-network binary and `uvx`/PyInstaller packaging won't do; (2) it's sold as a product, not
run as a service; (3) the *pipeline* modules go a full quarter without structural change
(catalogs/rules churning is fine — YAML ports for free). Trigger 3 + (1 or 2) = start.
There is **no performance case** — the scan time is already inside a Rust binary. Estimated
cost: 4–8+ weeks over ~6.3k prod + 5.7k test LOC.

**When triggered:** harden `drift-eval` with a byte-diff mode FIRST (score-identity permits
formatting drift); port engine-first as a standalone `drift-engine` crate injected via the
existing `run=` seam (hybrid path — proves the crates in-production while Python
orchestrates); renderers + `verify` last. **Port landmines to carry across, not
transliterate:** the `verify.py` lookbehind `(?<!\\)\|` (Rust `regex`/Go RE2 lack
lookbehind — rewrite it); float notation (`check_number_formats` guards this — Python
`1e+16` vs Go `10000000000000000`); Go map-order & `SetEscapeHTML(false)` if Go ever
resurfaces; and the tests' *comments* (each pins a real shipped bug — keep the prose).

## Branding

Tagline: *Know before it breaks.* Accent color: ember-crimson. Keep it plain and professional —
**no mascot or codename** (earlier mascot/codename experiments were retired as too informal for a
company tool).

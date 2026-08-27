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

- **Tests:** `.venv/bin/python -m pytest -q` (1440+, ~27s, no network — I/O is injected).
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

## The Rust rewrite happened, and it is not in this repository

**Do not start a Rust port here.** This section used to describe one as "banked — do NOT start
without a trigger", held behind a three-part trigger. That framework is **superseded, not
satisfied**: no trigger fired. What replaced it was a different decision — rebuild the product
clean under the strata design, in its own repository (**Almanac**, renamed from Drift Detector on
2026-08-19). Anyone who read the old section came away believing the opposite of what is
happening.

**This repository is the shipping Python scanner and stays that way.** It is feature-complete for
its job and in maintenance: fixes, catalog growth, and the occasional correctness change. The
rewrite does not block work here and work here does not block the rewrite — they share no code by
design, which is what makes "rebuilt, not ported" true in the filesystem rather than only in prose.

Two engineering facts from the old section are worth keeping, because they are about *this* code
and would otherwise be lost:

- **The engine is pinned deliberately.** `bin/drift-scan` fixes `AST_GREP_VERSION` and verifies a
  sha256, so two machines get the same scanner. Treat a bump as a ruleset re-verification event,
  not a dependency update.
- **Two portability landmines live in this tree** and are guarded, not incidental: `verify.py`'s
  lookbehind `(?<!\\)\|` (Rust's `regex` and Go's RE2 have no lookbehind), and float notation,
  which `check_number_formats` exists to police — Python emits `1e+16` where Go emits
  `10000000000000000`. Both guards should survive any future edit that touches them.

## Branding

Tagline: *Know before it breaks.* Accent color: ember-crimson. Keep it plain and professional —
**no mascot or codename** (earlier mascot/codename experiments were retired as too informal for a
company tool).

## Navigator / Worker protocol

When work is split between a planning agent and this one, the full protocol is in
`docs/NAVIGATOR-WORKER.md`. It exists because a fix once landed in the wrong clone —
tests green, report "done", nothing shipped. **This** repo is the shipping tree; product
fixes belong here, not in the orchestrator workspace.

**Worker standing orders:**

- Work ONLY in the absolute path the navigator names. If it is missing, STOP and report.
- FAILING test first → paste the failure → fix → paste the pass. No fix before red.
- Done report MUST include: `pwd`, `git log -1 --oneline`, test command + exit code, files changed.
- No scope expansion. No fixing a second tree unasked.
- No completion claims without those four evidence fields.

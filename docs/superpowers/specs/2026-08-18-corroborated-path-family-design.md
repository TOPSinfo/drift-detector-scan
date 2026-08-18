# Corroborated path families + the Go ecosystem — design

**Date:** 2026-08-18
**Status:** approved, not yet implemented
**Origin:** the standing "multi-language egress gap" open item, re-measured 2026-08-18

## Summary

Ship a vendor-scoped `path-constant` idiom that is guarded by **corroboration** (N distinct
path families co-occurring in a repo) instead of by `repo:` identity, and teach the scanner to
read `go.mod` as a new `go` ecosystem. Together these close the gap where a repo's API
operations are visible in its source but the scanner attributes none of them.

This is **not** a Go feature. The same path shapes appear in all eight languages; Go is
merely where the absence was most visible (0 of 5 corpus repos KNOWN).

## What was measured first

Re-ran the wild 40-repo corpus (same repos, same SHAs, `--now 2026-08-06` to isolate the
engine change from date drift). `verify` exits 0.

| run | attributed | note |
|---|---|---|
| baseline 2026-08-06, no overlay | 171 | |
| current engine, no overlay | 193 | engine-only gain is **+22** |
| current engine + local overlay | 585 | the rest is 7 hand-authored path-constant idioms |

The 585 figure must not be read as engine capability. `saleweaver/python-amazon-sp-api` is
7 → 8 from the engine and 8 → **389** from a single hand-authored YAML instance. That 48×
gain from one catalog entry is the core argument for this work.

`amzapi/selling-partner-api-sdk` (Go) was **0 attributed / 122 unattributed paths in all
three runs** — sinks did not close it, engine changes did not, and the overlay did not
(no Go instance existed).

## Key finding: the family was never language-gated

`path-constant` already compiles for every language:

- `idioms.to_rules`: `langs = [inst["language"]] if inst.get("language") else list(languages)`
  — omitting `language:` compiles the instance for **all** languages.
- `vendor_rules.AST_STRING_KINDS["go"] = ["interpreted_string_literal", "raw_string_literal"]`
  already exists and was verified empirically.
- `literal_rule` is generic across languages.

`rule_kinds_by_language()` reported `path-constant` for only php/js/python/ts because those
were the languages named by the seven *overlay* instances — not because of any code
restriction.

**Verified:** a trial Go instance took amzapi **0 → 102 attributed** with zero code changes,
producing **6 dated sunset findings, 4 already past their removal date**, each with file:line
and a vendor source URL:

| unit | retires |
|---|---|
| `/catalog/v0` | 2026-06-30 |
| `/fba/inbound/v0` | 2025-01-21 |
| `/fba/smallAndLight/v1` | 2024-03-27 |

Note these are the **generic** `/v0` and `/v1` paths. A "ship only distinctive date-versioned
paths" strategy would have found none of them.

## Key finding: the package cannot be the guard

A shipped family cannot be `repo:`-bound, so it needs another guard. The obvious candidate —
require the vendor's SDK in the manifest — was tested and **falsified**:

| case | paths in tree | SDK dep in go.mod | path-constant fires | dated findings |
|---|---|---|---|---|
| SDK repo itself (`amzapi`) | yes | n/a — *is* the SDK | yes (102) | 6 |
| hand-written client (fixture) | yes | **no** | yes (2) | 2 |
| consumer importing the SDK (fixture) | **no** | yes | cannot | 0 |

The two signals are **anti-correlated**. Where paths exist in-tree there is no SDK dependency
to guard on; where the SDK dependency exists the paths live in the module cache, not the repo.
A `requiresPackage:` guard would disable the rule exactly where it works and enable it exactly
where it has nothing to match.

The consumer case is not unserved — it returned `KNOWN` with vendor Amazon SP-API from the host
literal. What it lacks is *operation-level* detail, so no sunset joins. That is the existing
`sdk-only-no-callsite` blind spot, which `sdk_profiles.yaml` was built for.

Two lanes, two mechanisms.

## Lane 1 — corroborated path families

### Threshold calibration (evidence, not guesswork)

Counted distinct SP-API path families per repo across all 42 cloned corpus repos, 8 languages,
8 marketplace portals:

| distinct families | repos | identity |
|---|---|---|
| 9–16 | **10** | every one a genuine Amazon SP-API SDK |
| 0 | **32** | eBay, Walmart, Shopify, BigCommerce, Etsy, MercadoLibre, MWS |

No repo falls between 1 and 8. Worst true positive: 9. Worst false positive: 0.
**`corroboration: 3` carries a margin of 6 on one side and 3 on the other.**

### Schema

Add an optional `corroboration: <int>` to the `path-constant` family, plus a `families:` list
naming the alternation groups so distinctness is countable rather than re-derived from the
regex at match time.

`families:` and `pathRegex` state the same set twice, which is a drift hazard. Validation
closes it: the `families:` list MUST equal the alternation in `pathRegex`'s first capture
group, or the instance is rejected. Two sources of truth that cannot disagree are acceptable;
two that can are not.

Validation (`idioms._validate`) becomes: `vendor` + `pathRegex` + **exactly one of** `repo:` or
`corroboration:`. Never neither — an unguarded generic path family must remain impossible to
author. Never both — two guards on one instance means the weaker one is dead weight nobody
reviews.

### Enforcement

`endpoints.py` currently gates path-constant attribution on `_repo_in_scope`. Add the
corroboration path: count distinct matched families for the repo, attribute only at or above
the threshold. The existing sink guard and repo-scope guard are unchanged for `repo:` instances.

### The shipped instance

One SP-API instance, **no `language:` field**, so it compiles for all eight languages:

```yaml
- id: spapi-operation-paths
  family: path-constant
  vendor: Amazon SP-API
  corroboration: 3
  families: [authorization, catalog, fba, feeds, finances, listings, messaging, mfn,
             notifications, orders, products, reports, sales, sellers, service, shipping,
             solicitations, uploads]
  pathRegex: ^/(authorization|catalog|fba|feeds|finances|listings|messaging|mfn|notifications|orders|products|reports|sales|sellers|service|shipping|solicitations|uploads)/
  evidence: amzapi/selling-partner-api-sdk reports/api.gen.go:492
```

The `evidence:` line above is the one used in the verified trial. The absorb gate requires a
real file:line; it is not a template field.

## Lane 2 — the Go ecosystem

`lockfile.py` parses composer, npm, pypi and nuget. There is no Go, Ruby or Maven ecosystem.
Add `go.mod` as ecosystem `go`, which unlocks three things independently of Lane 1:

1. Go dependency inventory (currently entirely absent).
2. OSV Go advisories — Go packages presently get zero CVE coverage.
3. `sdk_clients` / `sdk_profiles` entries for the Go SP-API SDKs, so a **consumer** repo dates
   its operations instead of only naming its vendor.

## Staging

1. **`go.mod` parsing** — independent value, touches nothing in the idiom path.
2. **Corroboration guard** — schema, validation, enforcement.
3. **The shipped instance** — inert until step 2 exists.

## Testing

Per CLAUDE.md principle 5, each guard must be shown to FAIL on the bug it targets:

- A fixture repo containing a *single* generic SP-API-shaped path (e.g. an eBay repo with
  `/orders/v1/`) must not attribute — and the test must be demonstrated to fail when
  `corroboration` is removed, not merely written.
- The 9-vs-0 corpus separation becomes a regression assertion.
- Validation rejects a path-constant with neither `repo:` nor `corroboration:`, and one with
  both.
- Promote Go / Java / Ruby / C# repos into `eval/corpus.yaml`. It currently holds 34 repos with
  **zero** of those four languages (only `twilio-python` and `twilio-node` are non-PHP), so the
  eight-language sink coverage shipped earlier has no end-to-end regression guard at all. This
  closes a standing hole regardless of the rest of this work.
- `verify` exits 0 throughout.

## Open questions to settle during implementation

1. **Residue accounting.** `unattributedPaths` stayed at 122 even with 102 attributed
   (saleweaver: 389 attributed, 1159 residue). Either residue counts raw matches by design or
   this is a reporting bug. It drives the coverage tree, so settle it before shipping.
2. **Verdict semantics.** The verdict stays `UNKNOWN`/`config-driven-url` despite 102
   attributions and 6 dated findings. This is probably *correct* — the host genuinely is
   config-driven — but a repo with 6 dated findings rendering as UNKNOWN deserves a conscious
   decision rather than an accident.

## Non-goals

- Extending corroboration to other vendors in this change. The mechanism generalizes; the
  calibration does not. Each new vendor needs its own threshold evidence.
- Ruby / Maven ecosystems. Same shape of work as `go.mod`, deliberately deferred.
- Dataflow / sink→endpoint linking. Unchanged, still out of scope.

## Provenance

Measurement scripts and states: this session's scratchpad (`state-clean`, `state-new`,
`state-go-on`, `state-go-off`, `fixtures/`). Corpus and 2026-08-06 baseline:
`…/fa30e593-…/scratchpad/wild-corpus/`.

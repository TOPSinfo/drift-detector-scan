# Evaluating the scanner (`drift-eval`)

A contributor tool that measures the scanner against **real public code**, so a change to the
detection logic can be shown to improve or regress it — like evaluating prompts against a fixed set
of cases. Deterministic, zero-LLM. Not part of the end-user plugin.

## The idea

Ground truth is cheap here because of **category-by-construction**: we clone a repo *because* it's an
eBay (or SP-API, or Walmart) integration, so the assertion writes itself — it **must** detect that
vendor. The corpus (`eval/corpus.yaml`) pins each repo at a SHA for reproducibility; clones land in
`~/Projects/sandbox/<category>/` and are never committed.

## Run it

```bash
bin/drift-eval run ebay --now 2026-07-17        # clone (pin-verified) + scan + score
bin/drift-eval run sp --no-clone                # re-score already-cloned repos
```

Output — a scorecard, plus `scorecard.json` + a `history.jsonl` trend line under `~/.drift/eval/`:

```
RECALL   5/5 detect vendor   [PASS]     ← the hard gate; exit 1 if a non-known-gap repo misses
noise    median 1 · max 13 unknown hosts/repo         (info)
version  100% of 3 URL-versionable endpoints extracted · 21 have no URL version   (info)
sunset   1/1 expected fired                            (info)
```

**Recall is the only pass/fail.** Noise, version-rate, and sunset-match are informational and
trended. `version-rate` is measured only over endpoints whose URL actually carries a version, so the
scanner isn't penalized for APIs (Trading, Shopping, OAuth) that have none.

## Adding a repo or a category

Append to `eval/corpus.yaml` (validated on load; a malformed entry hard-fails):

```yaml
- repo: owner/name
  url: https://github.com/owner/name.git
  sha: "<40-hex — from `git ls-remote <url> HEAD`>"
  license: "<SPDX>"
  category: ebay
  expect: { vendor: eBay, sdk_keywords: [ebay], sunset_host: svcs.ebay.com }  # sunset_host optional
  known_gaps: [sdk-only-no-callsite]     # ONLY for a real, verified weakness (see eval/taxonomy.md)
  holdout: false                         # true = don't hand-tune the scanner to this repo
  fetched_at: "<YYYY-MM-DD>"
```

## The honesty rules (do not break these)

- **Never force the gate.** If a repo doesn't detect its vendor, investigate the *code*. Only three
  honest outcomes: (a) it's a real scanner weakness → add a truthful `known_gaps` from the
  [taxonomy](../eval/taxonomy.md); (b) the specimen is mislabeled (README says X, code doesn't call
  X) → **drop it** (`label-wrong`); (c) the vendor is genuinely uncatalogued → add a **generalizing**
  rule to `agent/vendors.yaml`, **never** the corpus repo's literal host (that's overfitting/Goodhart).
- **Recall gains are invalid if noise rises** — the scorecard prints noise beside recall for exactly
  this reason.
- **Pins are frozen.** Re-pinning a SHA is a deliberate, reviewed change; the runner hard-fails if a
  checkout's HEAD ≠ the pinned SHA.

## Tests

The scoring core (`agent/eval/score.py`) is a pure function, unit-tested with hand-built dicts. No
network in the unit suite. An opt-in live smoke (`DRIFT_EVAL_LIVE=1`) clones one real repo and runs
the real engine; it's skipped by default.

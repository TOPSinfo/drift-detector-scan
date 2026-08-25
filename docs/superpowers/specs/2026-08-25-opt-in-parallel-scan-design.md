# Opt-in parallel fleet scan (`--jobs N`)

**Date:** 2026-08-25
**Status:** design approved, not implemented

## Problem

A 53-repo fleet scan takes 15–25 minutes locally. Two phases dominate, and a third is
pure latency:

| Phase | Shape today | Cost |
|---|---|---|
| Per-repo AST sweep (`inventory_scan.scan_folder`) | serial `for` over discovered repos, each shelling out to `ast-grep` | the bulk |
| CVE lookups (`osv.query_all`) | dedupes to unique `(eco, name, version)`, then **one sequential `POST /v1/query` each** — 642 requests on the current fleet | minutes, and flaky |
| Fleet `git pull` (`run._pull_repos`) | serial `git pull --ff-only` per repo | 53 network round-trips |

The CVE phase is also the one that keeps emitting
`⚠ DEGRADED: 1 CVE source check failed this run`. 642 sequential requests is the shape that
trips rate limits, so this is not only a speed problem — it is a correctness problem, because
a degraded run reports fewer findings without being wrong on its face.

## Goal

Let a local run go faster. Let CI keep today's behaviour with no change to
`.gitlab-ci.yml` and no new way to be wrong.

## Non-goals

- Parallelising EOL lookups (`endoflife.date`) — a handful of distinct products
  (php, node, laravel). Not worth the surface area.
- Parallelising the audit, render, or deliver phases.
- Changing `.gitlab-ci.yml`. CI stays serial *by default*, not by configuration.

## The guarantee

`--jobs N` is a **pure scheduling knob**. Serial and parallel runs produce byte-identical
`drift.json`, `audit.json` and `drift.md`. A test proves it.

This is what makes the flag safe to exist: there is no "parallel mode" whose output anyone
has to reason about separately. `--jobs` changes *when* work happens, never *what is
concluded*.

### The one honest exception

The **progress log** is not identical. Under `--jobs 8` the `⚙ [n/53]` lines interleave by
completion order rather than repo order.

This is deliberate. The alternative — buffering each repo's line and flushing in index order —
would make the log *look* sequential while the work was not, which is a worse lie than an
honestly interleaved log. The artifacts are what the tool's claims rest on; the log is
progress feedback.

## Design

### `agent/lib/pool.py`

One function, no class, no configuration object:

```python
def ordered_map(fn, items, *, jobs=1, on_error=None) -> list:
    """Apply `fn` to each item, returning results in INPUT order regardless of
    completion order.

    jobs=1 takes a literal serial path — a plain loop, no executor constructed. The
    default is therefore not "a pool of size one" but today's code exactly, which is
    what keeps the CI risk at zero.
    """
```

Threads, not processes. Every parallelised unit either shells out (`ast-grep` via
`engine.run_scan`, `git pull`) or waits on a socket (OSV), so the GIL is released for the
duration of the work. Processes would add pickling and start-up cost for no gain.

### Call site 1 — per-repo AST sweep

`inventory_scan.scan_folder`'s `for i, (abs_, name) in enumerate(discovered)` becomes an
`ordered_map` over the same `discovered` list. Results are appended to `repos` in input
order, so `record["id"] = i + 1` and every downstream index stay exactly as they are.

The existing per-repo `try/except` is preserved verbatim — one repo erroring must still not
abort the sweep. Errors are captured per item and appended to `coverage["reposErrored"]` in
deterministic (input) order rather than completion order.

`coverage["reposScanned"]` and `coverage["manifestsUnparsed"]` are accumulated after the map
returns, from the ordered result list, rather than mutated inside the loop body.

**Thread-safety preconditions, verified:**

- `vendors`, `rules_path`, `rule_kinds`, `idiom_instances`, `attestations` are all loaded
  before the loop and only read inside it.
- `ir_store.save_repo_cache` writes a path derived from `(repo, head_sha, rules_sig)`, so
  every repo writes a distinct file. No contention.

### Call site 2 — fleet `git pull`

`run._pull_repos` maps over `discover_repos(roots)` through `ordered_map`. Lowest-risk
change in the set: each `git pull` touches only its own working tree.

### Call site 3 — OSV, rewritten rather than threaded

`query_all` stops calling `query_package` in a loop. Instead:

1. Chunk the deduped `(eco, name, version)` keys into `POST /v1/querybatch` requests.
   Chunk size is an implementation detail bounded by OSV's documented per-batch cap; it must
   not affect results, and test 5 covers a key set spanning more than one chunk to prove it.
2. Collect the returned vuln IDs. **`querybatch` returns only `{id, modified}`, not full
   records** — the normaliser needs `severity` and `summary`, so a second phase is required.
3. Dedupe the IDs across all packages (the same CVE recurs across repos — on the current
   fleet, 151 `DEPRECATED` + 221 `REVIEW` rows collapse to far fewer unique vulns) and fetch
   `GET /v1/vulns/{id}` for each unique ID, through `ordered_map`.
4. Reassemble `{(eco, name, version): [normalised vuln, ...]}` — the same return shape
   `query_all` produces today, so `audit.py` is untouched.

This phase helps **CI as well as local**, since the batching is a better API call rather than
concurrency. It is the highest-value part of this change and also the highest-risk, because
it alters what is asked of the API — hence the equivalence test below.

### Interface

`--jobs N` on `run` (and `inventory-scan`), default `1`. No environment variable, no
auto-detection: CI must not change behaviour because someone forgot to pin a value.

## Testing

Written test-first, per `superpowers:test-driven-development`.

1. `test_ordered_map_preserves_input_order_under_concurrency` — worker completion order
   deliberately shuffled (e.g. reverse-ordered sleeps); assert results match input order.
2. `test_ordered_map_captures_per_item_errors_without_aborting` — one item raises; the rest
   still complete and the error is reported against the right index.
3. `test_ordered_map_with_jobs_1_never_constructs_an_executor` — guards the "default is
   today's code" claim.
4. `test_serial_and_parallel_scans_produce_identical_output` — the multi-repo fixture in
   `tests/test_run_pipeline.py` run at `--jobs 1` and `--jobs 4`; assert **all three
   artifacts** named in the guarantee are equal (`drift.json`, `audit.json`, `drift.md`),
   not just `drift.json`. This is the test the whole guarantee rests on.
5. OSV equivalence — against a stub `http`, assert the batch+detail path normalises to the
   identical dicts the per-package path produces today, including the empty and
   unsupported-ecosystem cases.

## Risks

| Risk | Mitigation |
|---|---|
| OSV batch path normalises differently from per-package | Test 5 asserts dict-level equality against the current path |
| A shared object turns out to be mutated under threads | Preconditions verified above; test 4 would surface it as output divergence |
| `--jobs` accidentally becomes CI's default | No env fallback, no auto-detect; default is the literal serial path |
| Rate limiting simply moves from OSV `/query` to `/vulns/{id}` | Detail fetches are deduped first and are far fewer; if it recurs, cap `jobs` for that phase |

## Open question deferred

The `⚠ DEGRADED` warning is *expected* to improve, but this design does not promise it.
If batching does not fix it, the cause is elsewhere and gets its own investigation.

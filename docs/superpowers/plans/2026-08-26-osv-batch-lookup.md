# OSV Batch Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ~642 sequential `POST /v1/query` calls a fleet audit makes with a batched
`POST /v1/querybatch` pass plus a deduped, concurrent `GET /v1/vulns/{id}` detail fetch, producing
byte-identical findings.

**Architecture:** `agent/lib/osv.py` gains `query_batch(keys, ...)`, which chunks the key set into
`querybatch` requests, follows `next_page_token` until each query is exhausted, dedupes the
returned vuln ids across the whole fleet, fetches each unique id once through
`pool.ordered_map`, and normalises through the *same* helper `query_package` uses.
`agent/audit.py` gains a pre-pass that collects every `(eco, pkg, ver)` key across all repos
before the findings loop and primes `osv_cache` with the batch result; the findings loop itself is
untouched.

**Tech Stack:** Python 3.11+, stdlib only (`urllib` via `agent/lib/http_util.py`), PyYAML at
runtime; `pytest` for tests. `jsonschema` is test-only.

## Global Constraints

- **Runtime dependencies are stdlib + PyYAML only.** No `requests`, no `httpx`.
- **HTTP is injected.** Every network call goes through the `http=` parameter so tests pass canned
  callables and never touch the network. Never call `urllib` directly from `osv.py`.
- **Findings must be byte-identical to today's.** This phase changes *how* facts are fetched, never
  what is concluded. Task 5 is the gate.
- **"Cannot see" ≠ "clean" (principle 1).** A partial or failed lookup must degrade loudly through
  `coverage["osvErrors"]` and a note. Silently returning fewer vulns is the one unacceptable
  outcome.
- **Prove a guard against its bug (principle 5).** Every test in this plan must be seen to FAIL on
  the defect it targets before it is accepted.
- **Floats are banned by schema.** Not touched here, but do not introduce any.
- **No client identifiers in any file.** This is a public repo.

## Ground truth, verified before planning

Read these before writing code; the previous design document was wrong about all three.

1. **`osv.query_all` has ZERO production callers.** It is referenced only by
   `tests/test_osv.py:37` and by the old design doc. The real sequential loop is
   `agent/audit.py:186-196`, inside `audit_inventory`, which calls `osv.query_package` one package
   at a time and dedupes into its own local `osv_cache`. The old design's claim that
   "`audit.py` is untouched" is false — `audit.py` is the only place that can be batched.
2. **`POST /v1/querybatch` returns `id` and `modified` ONLY**, not full records
   (verified from OSV's own endpoint documentation). A second phase is mandatory because
   `_severity_label`, `_fixed_version`, `_source_url` and the summary all need the full record.
3. **There is no documented maximum queries per batch**, and the endpoint **paginates**:
   pagination triggers when one query returns more than 1,000 vulnerabilities *or the entire
   queryset returns more than 3,000 total*, and each result carries its own `next_page_token`.
   A fleet-scale queryset can hit the 3,000 trigger, so pagination is a correctness requirement,
   not an edge case.

Request shape:

```json
{"queries": [{"package": {"name": "axios", "ecosystem": "npm"}, "version": "0.21.1"}]}
```

Response shape — `results` is **index-aligned** to `queries`:

```json
{"results": [{"vulns": [{"id": "GHSA-x", "modified": "..."}], "next_page_token": "optional"}]}
```

## File Structure

- `agent/lib/osv.py` — **modified.** Gains `_normalise`, `query_batch`, `_fetch_details`,
  `OSV_QUERYBATCH_URL`, `OSV_VULN_URL`, `BATCH_CHUNK`. `query_package` keeps its exact current
  behaviour and becomes a thin wrapper over `_normalise`. `query_all` is deleted in Task 6.
- `agent/audit.py` — **modified**, one pre-pass inserted before the repo loop
  (around line 175, after `osv_cache: dict = {}`). The findings loop is not restructured.
- `tests/test_osv_batch.py` — **created.** Chunking, index alignment, pagination, detail dedupe,
  partial-failure degradation.
- `tests/test_osv_equivalence.py` — **created.** The gate: the batch path and the per-package path
  normalise to identical dicts.
- `tests/test_audit_osv_prepass.py` — **created.** The pre-pass primes the cache, preserves
  `osv_down` semantics, and leaves findings unchanged.
- `tests/test_osv.py` — **modified** in Task 6 only, to drop the `query_all` test.

---

### Task 1: Extract the normaliser `query_package` and the batch path will share

**Files:**
- Modify: `agent/lib/osv.py:70-89` (`query_package`)
- Test: `tests/test_osv.py` (existing tests must keep passing unchanged)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_normalise(v: dict, osv_eco: str | None, name: str | None) -> dict` — the single
  place a raw OSV vuln record becomes the six-key dict the audit consumes. Task 3 calls it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_osv.py`:

```python
def test_normalise_is_the_single_shape_authority():
    """Both lookup paths must produce the same dict from the same raw record, so the shape lives
    in one function. Called directly here so a future divergence between the per-package and the
    batch path fails at the seam rather than in a fleet diff."""
    raw = {
        "id": "GHSA-abc", "aliases": ["CVE-2020-1234"],
        "summary": "Server-side request forgery",
        "database_specific": {"severity": "HIGH"},
        "affected": [{"package": {"ecosystem": "npm", "name": "axios"},
                      "ranges": [{"events": [{"introduced": "0"}, {"fixed": "0.21.2"}]}]}],
        "references": [{"url": "https://example.test/advisory"}],
    }
    assert osv._normalise(raw, "npm", "axios") == {
        "id": "GHSA-abc",
        "cve": "CVE-2020-1234",
        "severity": "HIGH",
        "summary": "Server-side request forgery",
        "fixed": "0.21.2",
        "url": "https://example.test/advisory",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_osv.py::test_normalise_is_the_single_shape_authority -q`
Expected: FAIL with `AttributeError: module 'agent.lib.osv' has no attribute '_normalise'`

- [ ] **Step 3: Write the minimal implementation**

In `agent/lib/osv.py`, replace the body of `query_package`'s loop with a call to a new helper.
The helper is the existing dict literal, moved verbatim:

```python
def _normalise(vuln: dict, osv_eco: str | None = None, name: str | None = None) -> dict:
    """One raw OSV record -> the six keys the audit consumes. The ONLY place this shape is
    built: `query_package` and the batch path both go through here, so the two lookup routes
    cannot drift apart in what they claim about a vulnerability."""
    return {
        "id": vuln.get("id", ""),
        "cve": _cve(vuln),
        "severity": _severity_label(vuln),
        "summary": (vuln.get("summary") or (vuln.get("details") or "")[:160]).strip(),
        "fixed": _fixed_version(vuln, osv_eco, name),
        "url": _source_url(vuln),
    }


def query_package(eco: str, name: str, version: str | None, *, http=default_http) -> list:
    """Return a list of normalized vuln dicts for one package version (empty if none/unsupported).

    Kept as-is alongside the batch path: it is the equivalence ORACLE for
    tests/test_osv_equivalence.py, and the single-package path a caller with one key should still
    take rather than building a one-element batch."""
    osv_eco = osv_ecosystem(eco)
    if not osv_eco or not version:
        return []
    resp = http(OSV_QUERY_URL, method="POST",
                body={"package": {"ecosystem": osv_eco, "name": name}, "version": version})
    return [_normalise(v, osv_eco, name) for v in resp.get("vulns") or []]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_osv.py -q`
Expected: PASS, all tests including the pre-existing `test_query_package_normalizes_vuln` — that
one passing unchanged is the proof the extraction was behaviour-preserving.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1529 passed, 3 skipped` (1528 + the new test)

- [ ] **Step 6: Commit**

```bash
git add agent/lib/osv.py tests/test_osv.py
git commit -m "refactor(osv): one normaliser, so two lookup paths cannot drift

The batch path needs the same six-key dict query_package builds. Extracting it
now, before that path exists, means the shape has one authority rather than two
copies that agree on the day they were written.

query_package's own behaviour is unchanged, which its existing test proves by
passing untouched."
```

---

### Task 2: `query_batch` — chunking, index alignment, and pagination

**Files:**
- Modify: `agent/lib/osv.py`
- Test: `tests/test_osv_batch.py` (create)

**Interfaces:**
- Consumes: `_normalise` from Task 1.
- Produces: `_batch_ids(keys, *, http, chunk=BATCH_CHUNK) -> dict[tuple, list[str]]` — maps each
  `(eco, name, version)` key to the list of vuln ids OSV reports for it, in OSV's order, with all
  pages followed. Task 3 consumes this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_osv_batch.py`:

```python
"""POST /v1/querybatch returns ids only, index-aligned to the queries sent, and paginates when a
queryset is large. Each of those three is a way to silently under-report CVEs, which is the one
outcome principle 1 forbids: a missing vulnerability renders identically to a clean package."""
import pytest

from agent.lib import osv


def _resp(*id_lists, tokens=None):
    """A querybatch response for N queries, in query order."""
    results = []
    for i, ids in enumerate(id_lists):
        r = {"vulns": [{"id": x, "modified": "2026-01-01T00:00:00Z"} for x in ids]}
        if tokens and tokens.get(i):
            r["next_page_token"] = tokens[i]
        results.append(r)
    return {"results": results}


def test_batch_maps_ids_back_to_the_key_that_asked_for_them():
    """`results` is positional, not keyed. Mapping it back by anything other than index attributes
    one package's vulnerabilities to another."""
    keys = [("npm", "axios", "0.21.1"), ("npm", "lodash", "4.17.0"), ("pypi", "django", "3.0")]
    seen = {}

    def http(url, *, method="GET", body=None, timeout=20):
        seen["queries"] = body["queries"]
        return _resp(["GHSA-axios"], [], ["GHSA-dj1", "GHSA-dj2"])

    out = osv._batch_ids(keys, http=http)
    assert out[("npm", "axios", "0.21.1")] == ["GHSA-axios"]
    assert out[("npm", "lodash", "4.17.0")] == []
    assert out[("pypi", "django", "3.0")] == ["GHSA-dj1", "GHSA-dj2"]
    assert seen["queries"][1] == {"package": {"ecosystem": "npm", "name": "lodash"},
                                  "version": "4.17.0"}


def test_batch_splits_into_chunks_and_keeps_every_key():
    """A fleet sends far more keys than one request should carry. Chunking must not drop or
    reorder keys across the chunk boundary."""
    keys = [("npm", f"p{i}", "1.0") for i in range(5)]
    calls = []

    def http(url, *, method="GET", body=None, timeout=20):
        calls.append([q["package"]["name"] for q in body["queries"]])
        return _resp(*[[f"GHSA-{q['package']['name']}"] for q in body["queries"]])

    out = osv._batch_ids(keys, http=http, chunk=2)
    assert calls == [["p0", "p1"], ["p2", "p3"], ["p4"]]
    assert len(out) == 5
    assert out[("npm", "p4", "1.0")] == ["GHSA-p4"]


def test_batch_follows_next_page_token_until_exhausted():
    """OSV paginates when the whole queryset exceeds 3000 vulns. Stopping at page 1 loses real
    findings and reports the package as clean."""
    keys = [("npm", "big", "1.0")]
    pages = []

    def http(url, *, method="GET", body=None, timeout=20):
        tok = body["queries"][0].get("page_token")
        pages.append(tok)
        if tok is None:
            return _resp(["GHSA-1"], tokens={0: "tok-2"})
        if tok == "tok-2":
            return _resp(["GHSA-2"], tokens={0: "tok-3"})
        return _resp(["GHSA-3"])

    out = osv._batch_ids(keys, http=http)
    assert pages == [None, "tok-2", "tok-3"]
    assert out[("npm", "big", "1.0")] == ["GHSA-1", "GHSA-2", "GHSA-3"]


def test_batch_refuses_a_response_whose_results_do_not_line_up():
    """Fewer results than queries means the mapping is undefined. Guessing which key lost its
    result would attribute vulnerabilities to the wrong package; failing loudly degrades the whole
    OSV source instead, which the audit already knows how to report."""
    keys = [("npm", "a", "1.0"), ("npm", "b", "1.0")]

    def http(url, *, method="GET", body=None, timeout=20):
        return _resp(["GHSA-a"])            # one result for two queries

    with pytest.raises(ValueError, match="results"):
        osv._batch_ids(keys, http=http)


def test_batch_skips_unsupported_ecosystems_and_missing_versions_without_asking():
    """Same filter query_package applies, applied before the request rather than after, so an
    unsupported key never occupies a slot in the batch."""
    keys = [("go", "x", "1.0"), ("npm", "axios", None), ("npm", "axios", "0.21.1")]
    sent = []

    def http(url, *, method="GET", body=None, timeout=20):
        sent.extend(q["package"]["name"] for q in body["queries"])
        return _resp(["GHSA-axios"])

    out = osv._batch_ids(keys, http=http)
    assert sent == ["axios"]
    assert out[("go", "x", "1.0")] == []
    assert out[("npm", "axios", None)] == []
    assert out[("npm", "axios", "0.21.1")] == ["GHSA-axios"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_osv_batch.py -q`
Expected: FAIL, 5 errors, `AttributeError: module 'agent.lib.osv' has no attribute '_batch_ids'`

- [ ] **Step 3: Write the minimal implementation**

Add to `agent/lib/osv.py`, below `OSV_QUERY_URL`:

```python
OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"

# Queries per querybatch request. OSV documents NO maximum, so this is not an API limit and must
# not be described as one — it is a bound WE choose. It exists because OSV paginates once the
# whole queryset exceeds 3,000 vulnerabilities; smaller chunks keep most responses to a single
# page, which keeps the request count predictable. Pagination is still followed if it happens.
BATCH_CHUNK = 200
```

And the function:

```python
def _batch_ids(keys, *, http=default_http, chunk: int = BATCH_CHUNK) -> dict:
    """{(eco, name, version): [vuln id, ...]} for every key, in OSV's order, all pages followed.

    `querybatch` answers positionally: `results[i]` belongs to `queries[i]`. Nothing in the
    response identifies the package, so index is the ONLY correct join and a short `results`
    array is unrecoverable rather than merely odd — hence the ValueError.
    """
    out = {tuple(k): [] for k in keys}
    askable = [(tuple(k), osv_ecosystem(k[0])) for k in keys]
    askable = [(k, eco) for k, eco in askable if eco and k[2]]
    for i in range(0, len(askable), chunk):
        window = askable[i:i + chunk]
        # page_token is per-QUERY, so a page carries only the queries still unfinished
        pending = [{"package": {"ecosystem": eco, "name": k[1]}, "version": k[2]}
                   for k, eco in window]
        owners = [k for k, _eco in window]
        while pending:
            resp = http(OSV_QUERYBATCH_URL, method="POST", body={"queries": pending})
            results = resp.get("results") or []
            if len(results) != len(pending):
                raise ValueError(
                    f"OSV querybatch returned {len(results)} results for {len(pending)} queries — "
                    f"the index join is undefined, so no vulnerability can be attributed safely")
            nxt_q, nxt_owners = [], []
            for q, owner, res in zip(pending, owners, results, strict=True):
                out[owner].extend(v.get("id", "") for v in res.get("vulns") or [])
                token = res.get("next_page_token")
                if token:
                    nxt_q.append({**q, "page_token": token})
                    nxt_owners.append(owner)
            pending, owners = nxt_q, nxt_owners
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_osv_batch.py -q`
Expected: `5 passed`

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1534 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add agent/lib/osv.py tests/test_osv_batch.py
git commit -m "feat(osv): batch the id lookup, index-joined and fully paged

POST /v1/querybatch answers positionally — results[i] belongs to queries[i] and
nothing in the response names the package — so index is the only correct join
and a short results array is unrecoverable. It raises rather than guessing.

Pagination is followed per query, not per request: OSV pages once the whole
queryset passes 3,000 vulnerabilities, which a fleet-sized queryset reaches.
Stopping at page one would have reported real findings as absent.

BATCH_CHUNK is OUR bound, not an API limit: OSV documents no maximum."
```

---

### Task 3: Detail fetch, deduped across the fleet and fetched concurrently

**Files:**
- Modify: `agent/lib/osv.py`
- Test: `tests/test_osv_batch.py` (append)

**Interfaces:**
- Consumes: `_normalise` (Task 1), `_batch_ids` (Task 2), `pool.ordered_map` from
  `agent/lib/pool.py` — signature `ordered_map(fn, items, *, jobs=1) -> list[tuple[result, exc]]`.
- Produces: `query_batch(keys, *, http=default_http, jobs=1) -> dict[tuple, list[dict]]` — the same
  `{key: [normalised vuln]}` mapping `audit_inventory` builds today. Task 4 consumes this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_osv_batch.py`:

```python
def test_detail_is_fetched_once_per_unique_vuln_across_the_whole_fleet():
    """The same CVE recurs across repos and packages. Fetching it once per occurrence would
    replace 642 query calls with more detail calls than we started with."""
    keys = [("npm", "a", "1.0"), ("npm", "b", "1.0"), ("npm", "c", "1.0")]
    detail_calls = []

    def http(url, *, method="GET", body=None, timeout=20):
        if url.endswith("/querybatch"):
            return _resp(["GHSA-shared"], ["GHSA-shared"], ["GHSA-shared", "GHSA-only-c"])
        detail_calls.append(url)
        vid = url.rsplit("/", 1)[-1]
        return {"id": vid, "summary": f"summary for {vid}", "references": []}

    out = osv.query_batch(keys, http=http)
    assert len(detail_calls) == 2, f"expected 2 unique details, got {detail_calls}"
    assert [v["id"] for v in out[("npm", "a", "1.0")]] == ["GHSA-shared"]
    assert [v["id"] for v in out[("npm", "c", "1.0")]] == ["GHSA-shared", "GHSA-only-c"]


def test_a_detail_fetch_that_fails_raises_rather_than_dropping_the_vulnerability():
    """A vuln whose detail cannot be read is NOT a vuln that does not exist. Dropping it renders
    a vulnerable package as clean, which is the collapse principle 1 refuses. The audit's existing
    handler degrades the whole OSV source instead, and says so."""
    keys = [("npm", "a", "1.0")]

    def http(url, *, method="GET", body=None, timeout=20):
        if url.endswith("/querybatch"):
            return _resp(["GHSA-x"])
        raise OSError("connection reset")

    with pytest.raises(OSError):
        osv.query_batch(keys, http=http)


def test_batch_result_preserves_osv_order_within_a_key():
    """Findings are built by walking this list; a reordering would change drift.json for the same
    inputs, which the determinism principle forbids."""
    keys = [("npm", "a", "1.0")]

    def http(url, *, method="GET", body=None, timeout=20):
        if url.endswith("/querybatch"):
            return _resp(["GHSA-3", "GHSA-1", "GHSA-2"])
        vid = url.rsplit("/", 1)[-1]
        return {"id": vid, "summary": vid, "references": []}

    assert [v["id"] for v in osv.query_batch(keys, http=http)[("npm", "a", "1.0")]] == \
           ["GHSA-3", "GHSA-1", "GHSA-2"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_osv_batch.py -q -k "detail or preserves"`
Expected: FAIL, `AttributeError: module 'agent.lib.osv' has no attribute 'query_batch'`

- [ ] **Step 3: Write the minimal implementation**

Add the import at the top of `agent/lib/osv.py`, beside the existing ones:

```python
from agent.lib import cvss, pool
```

(replacing `from agent.lib import cvss`), and add:

```python
def query_batch(keys, *, http=default_http, jobs=1) -> dict:
    """{(eco, name, version): [normalised vuln, ...]} — the same mapping the per-package path
    builds, in two phases instead of one request per package.

    Phase 1 asks `querybatch` which vuln IDs each key has. Phase 2 fetches each UNIQUE id once:
    the same CVE recurs across repos and packages, so on a real fleet the id set is far smaller
    than the occurrence count — that collapse, not concurrency, is where the saving comes from.

    A detail fetch that fails PROPAGATES. A vulnerability whose record cannot be read is not a
    vulnerability that does not exist, and `audit_inventory` already knows how to degrade the OSV
    source loudly; silently omitting it would render a vulnerable package as clean.
    """
    ids_by_key = _batch_ids(keys, http=http, chunk=BATCH_CHUNK)
    unique = sorted({vid for ids in ids_by_key.values() for vid in ids if vid})
    outcomes = pool.ordered_map(lambda vid: http(OSV_VULN_URL + vid), unique, jobs=jobs)
    raw: dict = {}
    for vid, (rec, exc) in zip(unique, outcomes, strict=True):
        if exc is not None:
            raise exc
        raw[vid] = rec or {}
    out: dict = {}
    for key, ids in ids_by_key.items():
        eco = osv_ecosystem(key[0])
        out[key] = [_normalise(raw[vid], eco, key[1]) for vid in ids if vid]
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_osv_batch.py -q`
Expected: `8 passed`

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1537 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add agent/lib/osv.py tests/test_osv_batch.py
git commit -m "feat(osv): fetch each unique advisory once, concurrently

querybatch returns ids and modified only, so the normaliser still needs the full
record. Phase 2 fetches each UNIQUE id once: the same CVE recurs across repos and
packages, so the id set is far smaller than the occurrence count. That collapse
is where the saving comes from; ordered_map only overlaps the waiting.

A failed detail fetch propagates rather than being skipped. A vulnerability whose
record cannot be read is not a vulnerability that does not exist — audit_inventory
degrades the whole OSV source and says so, which is the honest rendering."
```

---

### Task 4: The `audit.py` pre-pass

**Files:**
- Modify: `agent/audit.py:160-200` (`audit_inventory`)
- Test: `tests/test_audit_osv_prepass.py` (create)

**Interfaces:**
- Consumes: `osv.query_batch` (Task 3).
- Produces: `audit_inventory(..., osv_batch=None)` — a new keyword argument, defaulting to
  `osv.query_batch`, resolved at call time so tests can monkeypatch it exactly as `osv_query` is.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audit_osv_prepass.py`:

```python
"""The 642 sequential requests live in audit_inventory, not in osv.query_all (which has no
production caller at all). Batching therefore needs a pre-pass here: collect every key across
every repo BEFORE the findings loop, so there is something to batch."""
from agent import audit as audit_mod


_DOC = {"repos": [
    {"path": "a", "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "resolved": "0.21.1"}]},
    {"path": "b", "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "resolved": "0.21.1"},
                           {"eco": "npm", "pkg": "lodash", "ver": "^4.17.0", "resolved": "4.17.0"}]},
]}


def test_the_prepass_asks_once_for_every_deduped_key_and_the_loop_asks_for_none():
    """One batch call for the whole fleet; zero per-package calls left behind."""
    batched, per_package = [], []

    def fake_batch(keys, *, http=None, jobs=1):
        batched.append(sorted(keys))
        return {tuple(k): [] for k in keys}

    def fake_query(*a, **k):
        per_package.append(a)
        return []

    audit_mod.audit_inventory(_DOC, "2026-08-26", osv_batch=fake_batch, osv_query=fake_query,
                              eol_check=lambda *a, **k: None, sunsets=[])
    assert len(batched) == 1, "the fleet must be asked for in ONE batch, not one per repo"
    assert batched[0] == [("npm", "axios", "0.21.1"), ("npm", "lodash", "4.17.0")], \
        "keys must be deduped across repos before the request"
    assert per_package == [], "no package may still take the one-at-a-time path"


def test_a_failed_batch_degrades_the_source_loudly_and_finds_nothing_silently():
    """Principle 1: a lookup that could not run must not render as a clean package."""
    def boom(keys, *, http=None, jobs=1):
        raise OSError("connection reset")

    out = audit_mod.audit_inventory(_DOC, "2026-08-26", osv_batch=boom,
                                    eol_check=lambda *a, **k: None, sunsets=[])
    assert out["coverage"]["osvErrors"] == 1
    assert any("OSV unreachable" in n for n in out["coverage"]["notes"])
    assert [f for f in out["findings"] if f["kind"] == "cve"] == []


def test_findings_are_identical_to_the_per_package_path():
    """The gate for this task: same vulns in, same findings out."""
    vuln = {"id": "GHSA-x", "cve": "CVE-2020-1", "severity": "HIGH", "summary": "s",
            "fixed": "0.21.2", "url": "https://example.test/a"}

    def fake_batch(keys, *, http=None, jobs=1):
        return {tuple(k): ([vuln] if k[1] == "axios" else []) for k in keys}

    def fake_query(eco, pkg, ver, *, http=None):
        return [vuln] if pkg == "axios" else []

    batched = audit_mod.audit_inventory(_DOC, "2026-08-26", osv_batch=fake_batch,
                                        eol_check=lambda *a, **k: None, sunsets=[])
    serial = audit_mod.audit_inventory(_DOC, "2026-08-26", osv_batch=None, osv_query=fake_query,
                                       eol_check=lambda *a, **k: None, sunsets=[])
    assert batched["findings"] == serial["findings"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_audit_osv_prepass.py -q`
Expected: FAIL — `TypeError: audit_inventory() got an unexpected keyword argument 'osv_batch'`

- [ ] **Step 3: Write the minimal implementation**

First, add a module-level sentinel near the top of `agent/audit.py`, beside the other
module constants:

```python
_UNSET = object()      # lets `osv_batch=None` MEAN "no batching", distinct from "not specified"
```

A plain `None` default cannot express both "caller said nothing, so batch" and "caller
deliberately wants the one-at-a-time path" — and Task 5 needs the second to use the per-package
route as its oracle.

Then change the signature (line 160):

```python
def audit_inventory(doc: dict, now: str, *, http=None,
                    osv_query=None, osv_batch=_UNSET, eol_check=None, sunsets=None) -> dict:
```

and immediately after `osv_query = osv_query or osv.query_package` add:

```python
    # Resolved at call time, like osv_query above, so a test can monkeypatch the module attribute.
    # `osv_batch=None` explicitly selects the one-at-a-time path — the equivalence oracle, and the
    # fallback if the batch endpoint ever has to be switched off in a hurry. Not specifying it
    # batches: `audit_inventory(doc, now)` takes the new route.
    osv_batch = osv.query_batch if osv_batch is _UNSET else osv_batch
```

Then insert the pre-pass immediately after `osv_cache: dict = {}` (line ~175, before
`osv_down = eol_down = False` is used in the loop):

```python
    osv_down = eol_down = False

    # --- OSV pre-pass: one batched lookup for the WHOLE fleet ------------------------------
    # The per-repo loop below still reads osv_cache exactly as it always did; this only fills it
    # in advance. Collected here rather than inside the loop because a batch needs every key
    # before the first request — which is the whole reason this is a pre-pass and not a swap of
    # one call for another.
    if osv_batch is not None:
        wanted = []
        for r in repos:
            for s in r.get("sdks", []):
                eco, pkg = s.get("eco"), s.get("pkg")
                ver = s.get("resolved") or floor(s.get("ver"))
                if osv_ecosystem(eco) is None or ver is None:
                    continue
                key = (eco, pkg, ver)
                if key not in osv_cache:
                    osv_cache[key] = None            # placeholder: dedupes the collection pass
                    wanted.append(key)
        if wanted:
            try:
                osv_cache.update(osv_batch(wanted, http=http))
            except Exception as exc:      # same degradation the per-package path already has
                osv_down = True
                coverage["osvErrors"] += 1
                coverage["notes"].append(f"OSV unreachable — package audit skipped ({exc}).")
            finally:
                # placeholders for keys the batch did not answer must not look like "no vulns"
                for k in wanted:
                    if osv_cache.get(k) is None:
                        osv_cache.pop(k, None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_audit_osv_prepass.py -q`
Expected: `3 passed`

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1540 passed, 3 skipped`. Pay attention to `tests/test_cli_dashboard.py`, which
monkeypatches `osv.query_package` — if it now fails, the pre-pass is reaching the network in a
test, which must be fixed here and not worked around in the test.

- [ ] **Step 6: Commit**

```bash
git add agent/audit.py tests/test_audit_osv_prepass.py
git commit -m "perf(audit): one batched OSV lookup for the fleet, not one per package

The 642 sequential requests were never in osv.query_all — that function has no
production caller. They are here, in audit_inventory's repo/sdk loop, one
query_package call at a time behind a local cache.

Batching therefore needs a PRE-PASS: every key across every repo, collected
before the first request, because a batch cannot be assembled lazily. The
findings loop below is untouched; it reads osv_cache exactly as it always did,
now pre-filled.

Degradation is unchanged and deliberately so: a failed batch sets osv_down,
counts an osvError and appends the same note, so 'could not look' still renders
differently from 'looked and found nothing'. Keys the batch did not answer have
their placeholder removed rather than left as an empty list, so a partial answer
cannot read as a clean package."
```

---

### Task 5: The equivalence gate

**Files:**
- Test: `tests/test_osv_equivalence.py` (create)

**Interfaces:**
- Consumes: `osv.query_package`, `osv.query_batch`.
- Produces: nothing. This is the gate the whole change rests on.

- [ ] **Step 1: Write the failing test**

Create `tests/test_osv_equivalence.py`:

```python
"""The batch path changes WHAT IS ASKED of the API, not what is concluded. This asserts the two
routes normalise to identical dicts — the same assertion the --jobs branch made for scheduling,
made here for a protocol change, which is the riskier of the two."""
from agent.lib import osv


_ADVISORIES = {
    "GHSA-full": {
        "id": "GHSA-full", "aliases": ["CVE-2021-9"], "summary": "Prototype pollution",
        "database_specific": {"severity": "CRITICAL"},
        "affected": [{"package": {"ecosystem": "npm", "name": "lodash"},
                      "ranges": [{"events": [{"introduced": "0"}, {"fixed": "4.17.21"}]}]}],
        "references": [{"url": "https://example.test/lodash"}],
    },
    "GHSA-cvss": {                      # severity derived from a vector, not a label
        "id": "GHSA-cvss", "aliases": [],
        "details": "no summary field at all, only details, which gets truncated to 160 chars",
        "severity": [{"score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
        "affected": [], "references": [],
    },
}


def _http(url, *, method="GET", body=None, timeout=20):
    if url.endswith("/query"):
        name = body["package"]["name"]
        ids = ["GHSA-full", "GHSA-cvss"] if name == "lodash" else []
        return {"vulns": [_ADVISORIES[i] for i in ids]}
    if url.endswith("/querybatch"):
        out = []
        for q in body["queries"]:
            ids = ["GHSA-full", "GHSA-cvss"] if q["package"]["name"] == "lodash" else []
            out.append({"vulns": [{"id": i, "modified": "2026-01-01T00:00:00Z"} for i in ids]})
        return {"results": out}
    return _ADVISORIES[url.rsplit("/", 1)[-1]]


def test_batch_and_per_package_normalise_identically():
    keys = [("npm", "lodash", "4.17.0"), ("npm", "axios", "0.21.1"), ("go", "unsupported", "1.0"),
            ("npm", "noversion", None)]
    batched = osv.query_batch(keys, http=_http)
    serial = {tuple(k): osv.query_package(k[0], k[1], k[2], http=_http) for k in keys}
    assert batched == serial


def test_equivalence_holds_across_a_chunk_boundary():
    """Chunking is an implementation detail; it must not be visible in the result."""
    keys = [("npm", "lodash", "4.17.0")] + [("npm", f"p{i}", "1.0") for i in range(6)]
    assert osv.query_batch(keys, http=_http) == \
           {tuple(k): osv.query_package(k[0], k[1], k[2], http=_http) for k in keys}
    # and again with a chunk size that forces a split mid-set
    osv.BATCH_CHUNK, saved = 2, osv.BATCH_CHUNK
    try:
        assert osv.query_batch(keys, http=_http) == \
               {tuple(k): osv.query_package(k[0], k[1], k[2], http=_http) for k in keys}
    finally:
        osv.BATCH_CHUNK = saved
```

- [ ] **Step 2: Run the test to verify it fails against a deliberately broken normaliser**

This gate must be seen to catch a real divergence, not merely pass. Temporarily change
`query_batch`'s `_normalise` call to drop the ecosystem argument
(`_normalise(raw[vid], None, key[1])`) — `_fixed_version` then matches a different `affected`
entry.

Run: `.venv/bin/python -m pytest tests/test_osv_equivalence.py -q`
Expected: FAIL on the `fixed` key. **Restore the argument before continuing.**

- [ ] **Step 3: No implementation needed**

The behaviour is already built. This task only adds the gate.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_osv_equivalence.py -q`
Expected: `2 passed`

- [ ] **Step 5: Run the full suite and a real fleet audit**

Run: `.venv/bin/python -m pytest -q` → `1542 passed, 3 skipped`

Then the real gate — the same inventory audited both ways must give the same `audit.json`:

```bash
cd /home/tops/Projects/tops/drift
export DRIFT_CATALOG_DIR="$PWD/drift-fleet/catalog"
PY="env PYTHONSAFEPATH=1 PYTHONPATH=$PWD/drift-detector-scan drift-detector-scan/.venv/bin/python"
# reuse an existing inventory.json rather than re-scanning for 10 minutes
$PY -m agent.cli audit --in <state>/inventory.json --now 2026-08-26 --out-json /tmp/ab/batch.json
# then with the batch path disabled, however Task 4's fallback is wired
diff /tmp/ab/batch.json /tmp/ab/serial.json && echo "IDENTICAL"
```

Expected: `IDENTICAL`, and the batch run measurably faster. **Record both wall times** — the
`--jobs` branch shipped an unproven speed claim, and this one must not.

- [ ] **Step 6: Commit**

```bash
git add tests/test_osv_equivalence.py
git commit -m "test: the batch and per-package paths must normalise identically

The guarantee this change rests on, asserted rather than argued: the same
advisories reached by either route produce the same dicts, including the empty
case, the unsupported ecosystem, the missing version, a severity derived from a
CVSS vector rather than a label, and a key set spanning a chunk boundary.

Seen to fail against a normaliser called without its ecosystem argument before
being accepted, per the repo's rule that a guard is proved against its bug."
```

---

### Task 6: Retire `query_all`

**Files:**
- Modify: `agent/lib/osv.py` (delete `query_all`)
- Modify: `tests/test_osv.py` (delete `test_query_all_dedupes_by_key`)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Prove it is unreachable before deleting it**

Run: `grep -rn "query_all" --include='*.py' . | grep -v '/.venv/'`
Expected: exactly two hits — its definition in `agent/lib/osv.py` and its test in
`tests/test_osv.py`. If anything else appears, STOP: it has a caller and this task is wrong.

- [ ] **Step 2: Delete both**

Remove `query_all` from `agent/lib/osv.py` and `test_query_all_dedupes_by_key` from
`tests/test_osv.py`.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1541 passed, 3 skipped` (one fewer than Task 5)

- [ ] **Step 4: Commit**

```bash
git add agent/lib/osv.py tests/test_osv.py
git commit -m "chore(osv): delete query_all — it never had a caller

Dead since it was written: the audit builds its own cache and calls
query_package directly. It survived because a test exercised it, which is how a
function with no production caller looks maintained. The design document for this
work was written against it and mis-scoped the whole change as a result.

query_batch now occupies that role, with a caller."
```

---

## Self-Review

**Spec coverage** — against the design doc's "Call site 3" section:

| Spec requirement | Task | Note |
|---|---|---|
| Chunk deduped keys into `querybatch` requests | Task 2 | chunk size is OURS; spec's "documented per-batch cap" does not exist |
| `querybatch` returns only `{id, modified}`; second phase required | Task 3 | confirmed from OSV's docs |
| Dedupe ids across packages, fetch each once | Task 3 | |
| Reassemble the `query_all` return shape | Task 3 + 4 | shape kept, but the consumer is `audit.py`, not `query_all` |
| "so `audit.py` is untouched" | **contradicted** | Task 4 — `audit.py` is the only place that can be batched |
| Test 5: batch normalises identically to per-package | Task 5 | incl. empty + unsupported-ecosystem cases |
| Pagination | **absent from the spec** | Task 2 — a correctness requirement at fleet scale |
| Parallelise EOL lookups | out of scope, per the spec's non-goals | |

**Placeholder scan:** none — every code step carries complete code. Task 5's step 5 leaves
`<state>` for the operator's own inventory path, which is an input, not an unwritten step.

**Type consistency:** `_batch_ids` returns `dict[tuple, list[str]]` and is destructured as
`ids_by_key.items()` in Task 3. `query_batch` returns `dict[tuple, list[dict]]`, matching what
`osv_cache` holds in Task 4 and what `query_package` returns per key. `pool.ordered_map` is
consumed as `list[tuple[result, exc]]`, matching its signature on `master`.

**Known weakness to raise at review:** Task 4's pre-pass duplicates the key-derivation logic
(`resolved or floor(ver)`, the `osv_ecosystem`/`None` filter) that the findings loop also
performs. If those two ever disagree, the pre-pass fetches keys the loop never asks for, or worse,
misses ones it does. Extracting a shared `_osv_keys_of(repo)` helper is the obvious fix and was
deliberately NOT done here, because doing it in the same commit as the batching would make the
diff span two concerns. It should be the first follow-up.

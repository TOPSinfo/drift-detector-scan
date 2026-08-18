# Corroborated Path Families Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a `path-constant` idiom ship in the baseline catalog guarded by *corroboration* (N distinct path families co-occurring in a repo) instead of by `repo:` identity, so Amazon SP-API operations attribute in any repo that carries them, in all eight languages.

**Architecture:** `agent/lib/idioms.py` gains a `corroboration:` alternative to `repo:` on the `path-constant` family (validated as mutually exclusive, with the `families:` list pinned to the `pathRegex` alternation). `agent/lib/endpoints.py` gains a pre-pass that counts distinct path families per instance per repo and admits attribution only at or above the threshold. One SP-API instance ships in `agent/idioms.yaml` with no `language:` field, so it compiles for every language.

**Tech Stack:** Python 3 (stdlib + PyYAML only at runtime), pytest, ast-grep via the pinned `bin/drift-scan` engine.

**Spec:** `docs/superpowers/specs/2026-08-18-corroborated-path-family-design.md`

## Global Constraints

- Runtime dependencies are **stdlib + PyYAML only**. `jsonschema` is test-only.
- The scan path is **deterministic and zero-token**. No wall-clock in logic; `now` is passed in.
- **Never invent a date.** Every retirement carries a `source:` URL fetched that session.
- A green `drift-scan verify` is the **only** correctness claim permitted. Never "it looks right".
- **Every guard must be shown to FAIL on the bug it targets** before it is trusted (CLAUDE.md principle 5). Reproduce first, then fix.
- Test suite baseline: `.venv/bin/python -m pytest -q` — **1321 passed, 3 skipped** at branch point (commit 24beb3d), ~25s, no network. CLAUDE.md still says "505+"; that figure is stale. Any drop from 1321 is a regression.
- Catalog YAML carries **load-bearing comments**; each entry records its provenance.

---

### Task 1: Corroboration schema and validation

**Files:**
- Modify: `agent/lib/idioms.py:93-101` (the `path-constant` branch of `_validate`)
- Modify: `agent/lib/idioms.py:14` (add `import re`)
- Test: `tests/test_idioms.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `path-constant` instances may now carry `corroboration: int` and `families: list[str]` instead of `repo: str`. `idioms.IdiomError` is raised for every malformed combination. Task 2 reads `inst.get("corroboration")` and `inst["families"]`; Task 4 authors an instance using them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_idioms.py`:

```python
# ── corroboration: the guard that lets a path-constant ship unbound from one repo ──
# A shipped family cannot be repo-scoped, but a generic /orders/v1 is not evidence of any
# vendor. Corroboration is the substitute: N DISTINCT path families must co-occur. Calibrated
# against 42 corpus repos — 10 genuine SP-API SDKs showed 9-16 families, the other 32 showed 0.

_CORR_INST = {"id": "spapi-operation-paths", "family": "path-constant",
              "vendor": "Amazon SP-API", "corroboration": 3,
              "families": ["catalog", "fba", "orders"],
              "pathRegex": r"^/(catalog|fba|orders)/",
              "evidence": "amzapi/selling-partner-api-sdk reports/api.gen.go:492"}


def test_validate_accepts_corroboration_instead_of_repo():
    idioms._validate(dict(_CORR_INST), "test")


def test_validate_rejects_path_constant_with_neither_repo_nor_corroboration():
    # THE BUG THIS GUARDS: an unguarded generic path family would attribute every repo's
    # /orders/ to whatever vendor the instance names. It must be impossible to author.
    inst = dict(_CORR_INST)
    del inst["corroboration"]
    del inst["families"]
    with pytest.raises(idioms.IdiomError, match="exactly one of"):
        idioms._validate(inst, "test")


def test_validate_rejects_path_constant_with_both_repo_and_corroboration():
    # Two guards on one instance means the weaker one is dead weight nobody reviews.
    inst = dict(_CORR_INST, repo="amzapi/selling-partner-api-sdk")
    with pytest.raises(idioms.IdiomError, match="exactly one of"):
        idioms._validate(inst, "test")


def test_validate_rejects_families_that_disagree_with_the_pathregex():
    # families: and pathRegex state the same set twice. Two sources of truth that CAN
    # disagree are a drift hazard; validation makes disagreement impossible.
    inst = dict(_CORR_INST, families=["catalog", "fba", "reports"])   # reports not in regex
    with pytest.raises(idioms.IdiomError, match="families"):
        idioms._validate(inst, "test")


def test_validate_rejects_a_corroboration_below_two():
    # corroboration: 1 is not corroboration — it is a single generic path, i.e. no guard.
    inst = dict(_CORR_INST, corroboration=1)
    with pytest.raises(idioms.IdiomError, match="corroboration"):
        idioms._validate(inst, "test")


def test_validate_rejects_a_corroborated_regex_without_an_alternation():
    inst = dict(_CORR_INST, pathRegex=r"^/catalog/", families=["catalog"])
    with pytest.raises(idioms.IdiomError, match="alternation"):
        idioms._validate(inst, "test")


def test_corroborated_instance_compiles_for_every_language():
    # No `language:` field -> to_rules falls back to the full language list. This is what
    # makes one shipped instance serve all eight languages.
    langs = ["php", "javascript", "typescript", "python", "ruby", "go", "java", "csharp"]
    docs = idioms.to_rules(dict(_CORR_INST), _literal_rule, langs)
    assert [d["language"] for d in docs] == langs
    assert all(d["metadata"] == {"kind": "path-constant", "vendor": "Amazon SP-API"}
               for d in docs)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_idioms.py -k corroborat -v`
Expected: FAIL. The `accepts` test fails with `IdiomError: ... path-constant needs \`repo\``; the rejection tests fail because no error is raised.

- [ ] **Step 3: Add the import**

In `agent/lib/idioms.py`, change:

```python
import os

import yaml
```

to:

```python
import os
import re

import yaml
```

- [ ] **Step 4: Replace the `path-constant` validation branch**

In `agent/lib/idioms.py`, replace this block:

```python
    if fam == "path-constant":
        # Repo-scoped + vendor-bound: a config-injected wrapper has no host literal, so the
        # vendor cannot be inferred from the repo — it must be NAMED (and reviewed), and the
        # instance must say which repo it applies to (the paths — `/api/orders` — are generic
        # and would mis-tag a different marketplace otherwise). pathRegex says which string
        # literals in that repo are operation paths.
        for req in ("repo", "vendor", "pathRegex"):
            if not inst.get(req):
                raise IdiomError(f"{where}: path-constant needs `{req}` — it is repo-scoped "
                                 "(generic paths would mis-tag another vendor) and vendor-bound "
                                 "(no host literal to infer the vendor from)")
```

with:

```python
    if fam == "path-constant":
        # Vendor-bound always: a config-injected wrapper has no host literal, so the vendor
        # cannot be inferred from the repo — it must be NAMED (and reviewed). pathRegex says
        # which string literals are operation paths.
        for req in ("vendor", "pathRegex"):
            if not inst.get(req):
                raise IdiomError(f"{where}: path-constant needs `{req}` — it is vendor-bound "
                                 "(no host literal to infer the vendor from)")
        # ...and GUARDED, by exactly one of two mechanisms. `repo` scopes the instance to one
        # repository (right for a client's private wrapper, whose generic /api/orders would
        # mis-tag another marketplace). `corroboration` scopes it by evidence instead, so the
        # instance can SHIP: N distinct path families must co-occur in the repo before any of
        # them attributes. Neither guard = a family that tags every repo's /orders/ with this
        # vendor. Both = the weaker one is dead weight nobody reviews.
        has_repo = bool(inst.get("repo"))
        has_corr = inst.get("corroboration") is not None
        if has_repo == has_corr:
            raise IdiomError(f"{where}: path-constant needs exactly one of `repo` "
                             "(scoped to one repository) or `corroboration` (scoped by "
                             "co-occurring evidence, so the instance can ship)")
        if has_corr:
            corr = inst["corroboration"]
            if not isinstance(corr, int) or isinstance(corr, bool) or corr < 2:
                raise IdiomError(f"{where}: `corroboration` must be an integer >= 2 — a "
                                 "threshold of 1 is a single generic path, i.e. no guard")
            fams = inst.get("families")
            if not isinstance(fams, list) or not fams:
                raise IdiomError(f"{where}: a corroborated path-constant needs `families` — "
                                 "the list of path segments whose DISTINCT count is compared "
                                 "against the threshold")
            # `families` and `pathRegex` state the same set twice. Pin them to each other so
            # they cannot drift: an edit to one that forgets the other fails the load loudly.
            m = _PC_ALTERNATION.match(inst["pathRegex"])
            if not m:
                raise IdiomError(f"{where}: a corroborated path-constant needs a pathRegex of "
                                 r"the form `^/(a|b|c)/` — the alternation is what makes "
                                 "families countable")
            if set(m.group(1).split("|")) != set(fams):
                raise IdiomError(f"{where}: `families` must equal the pathRegex alternation "
                                 f"— regex has {sorted(set(m.group(1).split('|')))}, "
                                 f"families has {sorted(set(fams))}")
```

- [ ] **Step 5: Add the alternation regex next to the other module constants**

In `agent/lib/idioms.py`, immediately after the `FAMILIES = frozenset({...})` definition, add:

```python
# `^/(catalog|fba|orders)/` -> the alternation body, so a corroborated instance's `families`
# list can be pinned to its own regex. Anchored deliberately: a corroborated family counts
# FIRST path segments, so the alternation has to be the first segment or the count is a lie.
_PC_ALTERNATION = re.compile(r"^\^?/\(([^)]+)\)/")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_idioms.py -v`
Expected: PASS, including the pre-existing repo-scoped tests (they still supply `repo:`, so `has_repo != has_corr` holds).

- [ ] **Step 7: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. If a pre-existing test authored a `path-constant` with neither guard, it was relying on the hole this task closes — fix the test by giving it `repo:`, and note that in the commit message.

- [ ] **Step 8: Commit**

```bash
git add agent/lib/idioms.py tests/test_idioms.py
git commit -m "feat(idioms): corroboration as an alternative guard to repo-scoping

A path-constant could only ship bound to one repo, because a generic
/orders/v1 is not evidence of any vendor. corroboration: N is the
substitute guard — N distinct path families must co-occur before any
attributes — so an instance can ship in the baseline catalog.

families: and pathRegex are pinned to each other; they state the same
set twice and would otherwise drift."
```

---

### Task 2: Corroboration enforcement in the endpoint pass

**Files:**
- Modify: `agent/lib/endpoints.py:279-313` (the path-constant attribution block)
- Test: `tests/test_endpoints.py`

**Interfaces:**
- Consumes: Task 1's `corroboration` / `families` fields on a path-constant instance.
- Produces: `scan_endpoints(...)` attributes a corroborated instance only when the repo shows at least `corroboration` distinct first path segments matching `pathRegex`. Below threshold, matches land in `out["residue"]["pathConstants"]` exactly as an out-of-scope instance does.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_endpoints.py`:

```python
# ── corroboration: a shipped path-constant guarded by evidence, not by repo identity ──
_SPAPI = Vendor("Amazon SP-API", "api:spapi", ("sellingpartnerapi-na.amazon.com",),
                DEFAULT_VERSION_REGEX)
_SPAPI_INST = {"id": "spapi-operation-paths", "family": "path-constant",
               "vendor": "Amazon SP-API", "corroboration": 3,
               "families": ["catalog", "fba", "orders", "reports"],
               "pathRegex": r"^/(catalog|fba|orders|reports)/",
               "evidence": "amzapi/selling-partner-api-sdk reports/api.gen.go:492"}


def _spc(path, line, text):
    return _pc(path, line, text, vendor="Amazon SP-API", check="spapi-operation-paths")


def test_corroborated_path_constant_attributes_when_the_threshold_is_met(tmp_path):
    # Four distinct families (catalog, fba, orders, reports) >= corroboration 3 -> attribute.
    ms = [_spc("catalog/api.go", 231, 'basePath := fmt.Sprintf("/catalog/v0/items")'),
          _spc("fbaInbound/api.go", 749, 'basePath := fmt.Sprintf("/fba/inbound/v0/shipments")'),
          _spc("ordersV0/api.go", 88, 'basePath := fmt.Sprintf("/orders/v0/orders")'),
          _spc("reports/api.go", 492, 'basePath := fmt.Sprintf("/reports/2021-06-30/reports")'),
          _sink("pkg/client.go", 40)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/anything.git")
    ops = {e["operation"] for e in out["endpoints"] if e["classified"]}
    assert ops == {"/catalog/v0/items", "/fba/inbound/v0/shipments",
                   "/orders/v0/orders", "/reports/2021-06-30/reports"}
    assert all(e["vendor"] == "Amazon SP-API"
               for e in out["endpoints"] if e["classified"])


def test_corroborated_path_constant_refuses_below_the_threshold(tmp_path):
    # THE BUG THIS GUARDS: an eBay repo with a single generic /orders/v1/ path must NOT be
    # tagged Amazon SP-API. Two distinct families < corroboration 3 -> nothing attributes,
    # and the paths land in residue so coverage stays honest rather than silently clean.
    ms = [_spc("src/orders.go", 12, 'p := fmt.Sprintf("/orders/v1/list")'),
          _spc("src/catalog.go", 30, 'p := fmt.Sprintf("/catalog/v1/item")'),
          _sink("src/client.go", 8)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/ebay-thing.git")
    assert [e for e in out["endpoints"] if e["classified"]] == []
    residue = {r["loc"] for r in out["residue"].get("pathConstants", [])}
    assert residue == {"src/orders.go:12", "src/catalog.go:30"}


def test_corroboration_counts_distinct_families_not_match_volume(tmp_path):
    # Twenty hits in ONE family is still one family. Volume is not corroboration — a repo
    # with a hundred /orders/ paths has said one thing loudly, not three things.
    ms = [_spc(f"src/o{i}.go", i, f'p := fmt.Sprintf("/orders/v1/x{i}")') for i in range(20)]
    ms.append(_sink("src/client.go", 8))
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/loud.git")
    assert [e for e in out["endpoints"] if e["classified"]] == []


def test_corroborated_path_constant_still_requires_an_egress_sink(tmp_path):
    # The sink guard is independent of the scoping guard and must survive it.
    ms = [_spc("catalog/api.go", 231, 'p := fmt.Sprintf("/catalog/v0/items")'),
          _spc("fbaInbound/api.go", 749, 'p := fmt.Sprintf("/fba/inbound/v0/s")'),
          _spc("ordersV0/api.go", 88, 'p := fmt.Sprintf("/orders/v0/orders")')]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/nosink.git")
    assert [e for e in out["endpoints"] if e["classified"]] == []


def test_corroborated_instance_needs_no_repo_field(tmp_path):
    # REGRESSION: the host fallback read inst['repo'] unconditionally, so a corroborated
    # instance (which has no `repo`) raised KeyError for any vendor with no domains.
    vendorless = Vendor("Amazon SP-API", "api:spapi", (), DEFAULT_VERSION_REGEX)
    ms = [_spc("catalog/api.go", 231, 'p := fmt.Sprintf("/catalog/v0/items")'),
          _spc("fbaInbound/api.go", 749, 'p := fmt.Sprintf("/fba/inbound/v0/s")'),
          _spc("ordersV0/api.go", 88, 'p := fmt.Sprintf("/orders/v0/orders")'),
          _sink("pkg/client.go", 40)]
    out = scan_endpoints(ms, str(tmp_path), [vendorless],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/anything.git")
    assert len([e for e in out["endpoints"] if e["classified"]]) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_endpoints.py -k "corroborat" -v`
Expected: FAIL. `test_corroborated_path_constant_attributes_when_the_threshold_is_met` fails with 0 classified endpoints, because `_repo_in_scope(repo_id, inst.get("repo", ""))` returns `False` for an empty suffix.

- [ ] **Step 3: Add the corroboration pre-pass**

In `agent/lib/endpoints.py`, immediately after this line:

```python
    has_sink = any(m.get("kind") == "sink" for m in matches)
```

insert:

```python
    # Corroboration pre-pass. The threshold is a property of the REPO, not of the match being
    # considered, so it has to be settled before any attribution happens — otherwise the first
    # match would be judged on evidence not yet counted. Counts DISTINCT first path segments:
    # twenty /orders/ hits are one family, not twenty, because volume is not corroboration.
    corroborated: set = set()
    _fams_seen: dict = {}
    for m in matches:
        if m.get("kind") != "path-constant":
            continue
        inst = pc_by_id.get(m.get("checkId"))
        if inst is None or inst.get("corroboration") is None:
            continue
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        path = _string_literal_of(m.get("text") or
                                  _read_line(repo_root, rel, lineno, line_cache))
        if not path or not re.search(inst["pathRegex"], path):
            continue
        seg = path.split("/")[1] if path.startswith("/") and "/" in path[1:] else ""
        if seg:
            _fams_seen.setdefault(inst["id"], set()).add(seg)
    for iid, fams in _fams_seen.items():
        if len(fams) >= int(pc_by_id[iid]["corroboration"]):
            corroborated.add(iid)
```

- [ ] **Step 4: Switch the guard to honour whichever scoping the instance declares**

In `agent/lib/endpoints.py`, replace:

```python
            if not _repo_in_scope(repo_id or repo_root, inst.get("repo", "")):
                continue
```

with:

```python
            # Exactly one of these two guards is present — idioms._validate enforces that.
            if inst.get("corroboration") is not None:
                if inst["id"] not in corroborated:
                    continue
            elif not _repo_in_scope(repo_id or repo_root, inst.get("repo", "")):
                continue
```

- [ ] **Step 5: Fix the host fallback for instances with no `repo`**

In `agent/lib/endpoints.py`, replace:

```python
            host = v.domains[0] if v.domains else f"sdk:{inst['repo']}"
```

with:

```python
            # A corroborated instance has no `repo`, so fall back to its id — reading
            # inst['repo'] unconditionally raised KeyError for a domainless vendor.
            host = v.domains[0] if v.domains else f"sdk:{inst.get('repo') or inst['id']}"
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_endpoints.py -v`
Expected: PASS, including every pre-existing repo-scoped path-constant test.

- [ ] **Step 7: Prove the guard fails on the bug it targets**

This is CLAUDE.md principle 5 and is not optional. Temporarily neuter the guard by editing the block from Step 4 to:

```python
            if inst.get("corroboration") is not None:
                pass          # TEMPORARY — proving the guard is load-bearing
            elif not _repo_in_scope(repo_id or repo_root, inst.get("repo", "")):
                continue
```

Run: `.venv/bin/python -m pytest tests/test_endpoints.py -k "refuses_below_the_threshold or counts_distinct_families" -v`
Expected: **BOTH FAIL** — the eBay repo is now tagged Amazon SP-API and the single-family repo attributes twenty endpoints. This is the bug the guard exists to prevent.

Now revert the edit (restore the Step 4 code exactly) and re-run:

Run: `.venv/bin/python -m pytest tests/test_endpoints.py -k "corroborat" -v`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add agent/lib/endpoints.py tests/test_endpoints.py
git commit -m "feat(endpoints): enforce corroboration for unbound path-constants

A corroborated instance attributes only where N distinct path families
co-occur. The count is a pre-pass because the threshold is a property of
the repo, not of the match being judged, and it counts distinct families
rather than match volume — twenty /orders/ hits are one family.

Shown to fail on its bug: with the guard neutered, an eBay repo carrying
one generic /orders/v1/ path is tagged Amazon SP-API.

Also fixes a KeyError: the host fallback read inst['repo'] unconditionally,
which a corroborated instance does not have."
```

---

### Task 3: Stop double-counting attributed paths as residue

**Files:**
- Modify: `agent/lib/endpoints.py:317-325` (the `path-literal` residue branch)
- Test: `tests/test_endpoints.py`

**Interfaces:**
- Consumes: `attributed_pc` (already built by the path-constant block).
- Produces: `out["residue"]["pathLiterals"]` no longer contains a location that a path-constant attributed. This is what makes `shapes.unattributedPaths` shrink when an idiom lands.

**Context:** This is open question 1 from the spec, now diagnosed. `residue_paths` excludes `attributed_locs` but not `attributed_pc`, so a line attributed by a path-constant still counts as unattributed path-literal residue. It is why the amzapi trial reported `attributed=102` while `unattributedPaths` stayed at 122, and why saleweaver reports 389 attributed against 1159 residue. The gate requires residue to SHRINK when an idiom is absorbed; today it does not.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_endpoints.py`:

```python
def test_a_path_constant_attribution_removes_the_line_from_path_literal_residue(tmp_path):
    # REGRESSION (the 102-attributed-but-122-still-residue bug): the same line can match both
    # a path-literal rule and a path-constant rule. Residue excluded only `attributed_locs`,
    # so a line the idiom HAD attributed was still reported as unattributed. Residue is the
    # conscience — it must shrink when an idiom lands, or the absorb gate cannot see progress.
    loc_text = 'basePath := fmt.Sprintf("/catalog/v0/items")'
    ms = [_spc("catalog/api.go", 231, loc_text),
          {"kind": "path-literal", "path": "catalog/api.go", "line": 231, "text": loc_text},
          _spc("fbaInbound/api.go", 749, 'p := fmt.Sprintf("/fba/inbound/v0/s")'),
          _spc("ordersV0/api.go", 88, 'p := fmt.Sprintf("/orders/v0/orders")'),
          _sink("pkg/client.go", 40)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/anything.git")
    assert any(e["operation"] == "/catalog/v0/items"
               for e in out["endpoints"] if e["classified"])
    assert "catalog/api.go:231" not in {r["loc"]
                                        for r in out["residue"].get("pathLiterals", [])}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_endpoints.py -k removes_the_line_from_path_literal_residue -v`
Expected: FAIL — `catalog/api.go:231` is present in `residue["paths"]` despite having been attributed.

- [ ] **Step 3: Exclude path-constant attributions from path-literal residue**

In `agent/lib/endpoints.py`, replace:

```python
        if kind == "path-literal" and loc not in attributed_locs:
```

with:

```python
        # `attributed_pc` too: one line can match both a path-literal rule and a path-constant
        # rule, and a line the idiom attributed is not unattributed. Counting it twice made
        # residue immovable — absorbing an idiom left unattributedPaths unchanged, so the gate
        # could not tell a working instance from a no-op.
        if kind == "path-literal" and loc not in attributed_locs and loc not in attributed_pc:
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_endpoints.py -k removes_the_line_from_path_literal_residue -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. A test asserting an exact residue count for a repo with path-constant attributions may now report a smaller number — that is this fix working. Update the expected number and note in the commit that the old value counted attributed lines.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/endpoints.py tests/test_endpoints.py
git commit -m "fix(endpoints): stop counting path-constant attributions as residue

One line can match both a path-literal and a path-constant rule. Residue
excluded attributed_locs but not attributed_pc, so an attributed line was
still reported unattributed — amzapi showed 102 attributed with residue
stuck at 122, and saleweaver 389 against 1159.

Residue is the conscience: it has to shrink when an idiom lands, or the
absorb gate cannot distinguish a working instance from a no-op."
```

---

### Task 4: Ship the Amazon SP-API path family

**Files:**
- Modify: `agent/idioms.yaml` (append the instance)
- Test: `tests/test_idioms.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: a baseline instance `spapi-operation-paths` that every scan loads. After this task `vendor_rules.rule_kinds_by_language()` reports `path-constant` for all eight languages.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_idioms.py`:

```python
def test_shipped_spapi_instance_loads_and_is_corroborated():
    # The first path-constant to ship in the BASELINE catalog. It must be corroboration-
    # guarded (a repo-scoped instance cannot ship) and language-agnostic.
    shipped = {i["id"]: i for i in idioms.load_idioms(idioms._DEFAULT)}
    inst = shipped["spapi-operation-paths"]
    assert inst["family"] == "path-constant"
    assert inst["vendor"] == "Amazon SP-API"
    assert inst.get("repo") is None, "a shipped instance must not be repo-scoped"
    assert inst["corroboration"] >= 3
    assert "language" not in inst, "omitting language is what serves all eight languages"
    idioms._validate(inst, "agent/idioms.yaml")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_idioms.py -k shipped_spapi -v`
Expected: FAIL with `KeyError: 'spapi-operation-paths'`.

- [ ] **Step 3: Append the instance to `agent/idioms.yaml`**

```yaml
# ── Amazon SP-API operation paths ────────────────────────────────────────────────────────
# The first path-constant to SHIP. Every earlier one is repo-scoped, because a generic
# `/api/orders` would mis-tag another marketplace. This one is guarded by corroboration
# instead: at least 3 of the 18 SP-API path families must co-occur before any attributes.
#
# THRESHOLD PROVENANCE (measured 2026-08-18 over 42 cloned corpus repos, 8 languages, 8
# marketplace portals — eBay, Walmart, Shopify, BigCommerce, Etsy, MercadoLibre, MWS, SP-API):
#   10 repos carried SP-API path families — every one a genuine Amazon SP-API SDK — with a
#      DISTINCT-family count between 9 and 16.
#   32 repos carried ZERO.
#   No repo fell between 1 and 8. A threshold of 3 sits 6 below the worst true positive and
#   3 above the worst false positive.
#
# No `language:` — path shapes are identical across languages, and omitting the field compiles
# the instance for all eight. Verified on Go (amzapi/selling-partner-api-sdk): 0 -> 102
# attributed, yielding 6 dated SP-API sunsets, 4 of them already past their removal date.
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

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_idioms.py -k shipped_spapi -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite and reconcile the language-coverage assertion**

Run: `.venv/bin/python -m pytest -q`
Expected: a test pinning `rule_kinds_by_language()` may now fail, because `path-constant` appears for all eight languages instead of none in a clean checkout. That is this task working. Update the expected mapping and add a comment recording that the shipped SP-API instance is what supplies `path-constant` everywhere.

- [ ] **Step 6: Commit**

```bash
git add agent/idioms.yaml tests/test_idioms.py
git commit -m "feat(catalog): ship the Amazon SP-API operation-path family

The first path-constant that is not bound to a single repo. Guarded by
corroboration: 3, calibrated over 42 corpus repos where 10 genuine SP-API
SDKs showed 9-16 distinct families and the other 32 showed zero.

No language: field, so one instance serves all eight languages. Verified
on Go: amzapi 0 -> 102 attributed, 6 dated sunsets, 4 already past due."
```

---

### Task 5: Attribute Go SP-API SDK consumers from the manifest

**Files:**
- Modify: `agent/sdk_clients.yaml`
- Test: `tests/test_sdk_clients.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — this lane is independent and may land in any order.
- Produces: a repo whose `go.mod` requires a catalogued SP-API Go SDK gets vendor attribution from the manifest, `attribution: sdk-client`.

**Context:** No code is needed. `agent/lib/extractors/go.py` already emits `tech_key="lib:go/<module>"`, and `sdk_clients._pkg_key()` maps that to `go/<module>`, which is exactly the map key. Verified by unit check on 2026-08-18. This covers the complementary case to Task 4: a consumer repo has the SDK in `go.mod` but no path literals in-tree, because they live in the module cache.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sdk_clients.py`:

```python
def test_go_module_techkeys_join_the_client_map():
    # Go needed no code: extractors/go.py emits lib:go/<module> and _pkg_key maps it to
    # go/<module>, which is the map key. This pins that the catalog rows are reachable.
    clients = sdk_clients.load()
    assert "go/github.com/amzapi/selling-partner-api-sdk" in clients
    key = sdk_clients._pkg_key("lib:go/github.com/amzapi/selling-partner-api-sdk")
    assert key == "go/github.com/amzapi/selling-partner-api-sdk"
    assert clients[key]["vendor"] == "Amazon SP-API"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sdk_clients.py -k go_module_techkeys -v`
Expected: FAIL — the key is absent from the map.

- [ ] **Step 3: Append the Go rows to `agent/sdk_clients.yaml`**

```yaml
# ── Marketplace / Amazon SP-API (Go) ─────────────────────────────────────────────────────
# A consumer repo requires one of these in go.mod but holds NO SP-API path literals of its
# own — the paths live in the module cache, which is not scanned. The dependency IS the
# evidence, exactly as for composer/twilio/sdk. This is the complement of the shipped
# `spapi-operation-paths` idiom, which needs the paths to be in-tree.
- { package: go/github.com/amzapi/selling-partner-api-sdk, vendor: Amazon SP-API, host: sellingpartnerapi-na.amazon.com }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sdk_clients.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm `Amazon SP-API` is a known vendor name**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import yaml; print([v['vendor'] for v in yaml.safe_load(open('agent/vendors.yaml')) if 'SP-API' in v['vendor']])"`
Expected: `['Amazon SP-API']`. The `vendor:` value must match `agent/vendors.yaml` exactly or the attestation and coverage joins miss. If it prints `[]`, stop and reconcile the name rather than inventing one.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/python -m pytest -q
git add agent/sdk_clients.yaml tests/test_sdk_clients.py
git commit -m "feat(catalog): attribute Go SP-API SDK consumers from go.mod

A consumer repo has the SDK in go.mod but no SP-API path literals in-tree,
because they live in the module cache. The dependency is the evidence.

No code needed: extractors/go.py already emits lib:go/<module> and
sdk_clients keys on <ecosystem>/<name> generically."
```

---

### Task 6: Give the non-PHP languages an end-to-end regression guard

**Files:**
- Modify: `eval/corpus.yaml`

**Interfaces:**
- Consumes: Tasks 1-4 (the SP-API repos should now attribute).
- Produces: four corpus cases in languages the corpus has never covered.

**Context:** `eval/corpus.yaml` holds 34 repos, of which only `twilio-python` and `twilio-node` are non-PHP. There is **no** Go, Java, Ruby, or C# case, so the eight-language egress-sink coverage shipped earlier has no end-to-end guard at all. This closes that hole and pins the new family across four languages at once. SHAs below were read from the pinned corpus clones on 2026-08-18.

- [ ] **Step 1: Append the four cases to `eval/corpus.yaml`**

```yaml
# ── Amazon SP-API across the languages the corpus never covered ──────────────────────────
# Added 2026-08-18. Until now the corpus was 34 repos of which only twilio-python and
# twilio-node were non-PHP, so the egress sinks shipped for all eight languages had NO
# end-to-end regression guard. These four also pin the shipped `spapi-operation-paths`
# family in four languages at once. SHAs read from the pinned corpus clones.
- repo: amzapi/selling-partner-api-sdk
  url: https://github.com/amzapi/selling-partner-api-sdk.git
  sha: "2d9166b756fd114f17286169e5b0f6c2b00db379"
  license: MIT
  category: spapi
  expect: { vendor: Amazon SP-API, sdk_keywords: [selling-partner] }
  holdout: false
  fetched_at: "2026-08-18"

- repo: amzn/selling-partner-api-samples
  url: https://github.com/amzn/selling-partner-api-samples.git
  sha: "8ac80bca2fe29f467d442be45f5f39ca12dfc7a6"
  license: MIT-0
  category: spapi
  expect: { vendor: Amazon SP-API, sdk_keywords: [selling-partner] }
  holdout: false
  fetched_at: "2026-08-18"

- repo: lineofflight/peddler
  url: https://github.com/lineofflight/peddler.git
  sha: "4e4d872d349e9ec21facb89f8df92b1c9cc78b2b"
  license: MIT
  category: spapi
  expect: { vendor: Amazon SP-API, sdk_keywords: [peddler] }
  holdout: false
  fetched_at: "2026-08-18"

- repo: abuzuhri/Amazon-SP-API-CSharp
  url: https://github.com/abuzuhri/Amazon-SP-API-CSharp.git
  sha: "ba22ba0a98a8cddb8919bfe1d801bbce2c34da74"
  license: MIT
  category: spapi
  expect: { vendor: Amazon SP-API, sdk_keywords: [selling-partner] }
  holdout: false
  fetched_at: "2026-08-18"
```

- [ ] **Step 2: Verify each declared license against the repo before trusting the rows**

Run: `.venv/bin/python -m pytest tests/test_eval_corpus.py -q`
Expected: PASS. If the corpus test validates licenses or required fields and one of the four is wrong, correct the row from the repo's own LICENSE file. Do not guess a license — an unverifiable one is the same class of error as an unsourced date.

- [ ] **Step 3: Run the full suite and commit**

```bash
.venv/bin/python -m pytest -q
git add eval/corpus.yaml
git commit -m "test(corpus): add Go, Java, Ruby and C# SP-API cases

The corpus was 34 repos with only two non-PHP entries, so the egress sinks
shipped for all eight languages had no end-to-end regression guard. These
four close that and pin the shipped SP-API path family across four
languages at once."
```

---

### Task 7: Verify against the real corpus and settle the verdict question

**Files:**
- Modify: `docs/superpowers/specs/2026-08-18-corroborated-path-family-design.md` (record the decision)
- Test: `tests/test_endpoints.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a measured before/after on the 40-repo corpus and a recorded decision on verdict semantics.

- [ ] **Step 1: Re-run the wild corpus with the shipped catalog**

The corpus clones and the pinned root list live in the scratchpad from the measurement session. Run with the overlay **disabled**, so the result reflects the shipped catalog alone and not the local private overlay — mixing the two is what produced the misleading 585 figure during design:

`mapfile` is a bash builtin and this machine's shell is zsh, so run this as a script under
bash — invoking it directly in the interactive shell silently passes NO roots and scans only
the current directory (this exact mistake happened during the design measurement):

```bash
cat > /tmp/drift-corpus-run.sh <<'EOF'
#!/usr/bin/env bash
set -eu
W=/tmp/claude-1000/-home-tops-Projects-tops-deprication-agent/fa30e593-ae4a-40f9-876e-558d40625a62/scratchpad/wild-corpus
cd /home/tops/Projects/tops/drift/drift-detector-scan
mapfile -t ROOTS < <(W="$W" python3 -c "
import json, os
W = os.environ['W']
for s in json.load(open(W + '/state/drift.json'))['shapes']:
    print(W + '/repos/' + s['repo'])
")
echo "roots=${#ROOTS[@]}"          # must print 40
ARGS=(); for r in "${ROOTS[@]}"; do ARGS+=(--root "$r"); done
DRIFT_CATALOG_DIR="" ./bin/drift-scan run "${ARGS[@]}" --state /tmp/drift-verify --now 2026-08-06
EOF
bash /tmp/drift-corpus-run.sh
```

Expected: `roots=40` before the scan output. If it prints `roots=0`, the root list failed to
build — stop, because the run below would measure nothing.

Expected: the run completes and reports more action-required findings than the 55 the engine-only control produced on 2026-08-06.

- [ ] **Step 2: Run the verify gate — the only correctness claim**

```bash
./bin/drift-scan verify --state /tmp/drift-verify; echo "EXIT=$?"
```

Expected: `EXIT=0`. A non-zero exit blocks this task; do not proceed and do not describe the report as correct.

- [ ] **Step 3: Confirm the SP-API repos moved and nothing else did**

```bash
python3 - <<'PY'
import json
W="/tmp/claude-1000/-home-tops-Projects-tops-deprication-agent/fa30e593-ae4a-40f9-876e-558d40625a62/scratchpad/wild-corpus"
base={s['repo']:s for s in json.load(open(W+"/state/drift.json"))['shapes']}
new={s['repo']:s for s in json.load(open("/tmp/drift-verify/drift.json"))['shapes']}
for r in sorted(new):
    b,n=base.get(r,{}),new[r]
    if b.get('attributed') != n.get('attributed'):
        print(f"{r[:46]:46} {b.get('attributed')} -> {n.get('attributed')}")
PY
```

Expected: the 10 SP-API repos gain attribution. **Any non-SP-API repo that gains attribution is a false positive and must be investigated before this ships** — that is the corroboration guard failing in the wild, and it outranks every other result here.

- [ ] **Step 4: Record the verdict-semantics decision**

The amzapi trial attributed 102 endpoints and produced 6 dated findings while the repo still reported `verdict: UNKNOWN` / `config-driven-url`. That is **correct and deliberate**: the host genuinely is injected at runtime, so the scanner cannot claim it has seen the repo's full egress. Attribution of operations is not the same claim as coverage of the repo.

Append to the spec's open-questions section, replacing question 2:

```markdown
2. **Verdict semantics — SETTLED 2026-08-18.** A repo may report `UNKNOWN` /
   `config-driven-url` while carrying attributed operations and dated findings. This is
   correct: the verdict describes whether the scanner could see the repo's egress, and a
   config-injected host means it could not. Attributing operations is a narrower claim than
   covering the repo, and conflating them would let "we dated six findings" masquerade as
   "we saw everything". Pinned by
   `test_corroborated_repo_with_findings_still_reports_unknown`.
```

- [ ] **Step 5: Pin that decision with a test**

Append to `tests/test_endpoints.py`:

```python
def test_corroborated_repo_with_findings_still_reports_unknown(tmp_path):
    # DELIBERATE, not an oversight: attributing operations is a narrower claim than covering
    # the repo. The host is still config-injected, so the scanner cannot say it saw this
    # repo's egress. Conflating the two would let "we dated six findings" read as "we saw
    # everything" — the exact failure principle 1 exists to prevent.
    ms = [_spc("catalog/api.go", 231, 'p := fmt.Sprintf("/catalog/v0/items")'),
          _spc("fbaInbound/api.go", 749, 'p := fmt.Sprintf("/fba/inbound/v0/s")'),
          _spc("ordersV0/api.go", 88, 'p := fmt.Sprintf("/orders/v0/orders")'),
          _sink("pkg/client.go", 40)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/anything.git")
    assert len([e for e in out["endpoints"] if e["classified"]]) == 3
    assert out["residue"].get("sinks"), \
        "the unresolved sink is what keeps the verdict honest about config-driven egress"
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tests/test_endpoints.py docs/superpowers/specs/2026-08-18-corroborated-path-family-design.md
git commit -m "test: pin verdict semantics for corroborated repos; verify on the corpus

A repo can carry attributed operations and dated findings while still
reporting UNKNOWN/config-driven-url. That is correct — the verdict is about
whether we could see the repo's egress, not about whether we dated
something in it. Settles spec open question 2.

Corpus re-run with the overlay disabled; verify exits 0."
```

---

## Notes for the implementer

- **Run with `DRIFT_CATALOG_DIR=""` whenever measuring.** The default overlay is `~/.drift/catalog`, which on this machine holds 7 private hand-authored path-constant instances. A measurement that inherits them overstates the shipped catalog badly — during design this produced a 585 figure where the true engine number was 193.
- **Do not edit `~/.drift/catalog`.** It is the user's private overlay and holds client data.
- **The `families` list and `pathRegex` must be edited together.** Task 1's validation rejects the instance if they disagree, so a partial edit fails loudly at load rather than silently narrowing detection.
- Tasks 5 and 6 are independent of 1-4 and of each other; only Tasks 1 → 2 → 3 → 4 are ordered.

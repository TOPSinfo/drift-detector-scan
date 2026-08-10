# Host-Triage Taxonomy (M1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the "wall of unknowns" into a triaged, ranked host classification — deterministically — so real API leads rise above noise (icons, CDNs, analytics, vendored UI kits) on *every* project, without abandoning the honesty principle.

**Architecture:** Add a single `hostClass` field to every endpoint record. It's computed by a new deterministic classifier (`host_class.py`) from two catalog/rules sources, zero AI: (1) a reviewed `host_reputation.yaml` (which folds in today's *silently-dropped* `_IGNORE` set plus a pinned public tracker/CDN list), and (2) URL-shape + call-context heuristics. The cockpit then groups unclassified endpoints by `hostClass` — real API leads on top, noise collapsed — and `verify` gains an invariant that every endpoint is classed and the buckets agree with the payload. The whole deterministic pipeline stays byte-identical and zero-token.

**Tech Stack:** Python 3.11+ (stdlib + PyYAML only — runtime). ast-grep engine unchanged. Vue 3 cockpit (existing, in-DOM template). `jsonschema` test-only.

**Where this is going (roadmap — NOT this plan):** M1 (this plan) is the deterministic floor. It is Phase 1 of Fable 5's "triage-first scan" direction. Phases planned *separately after M1 lands*: **M3** coverage-receipt lead card + empty-state copy; **M2** scan-scope guardrail (`origin` tagging + built-copy/UI-template detection); **AI agents** (Recon characterizes the `api-lead` bucket, Shaper drafts staged shapes) grounded on the deterministic tools + the `absorb` gate. M1 makes all of those cheaper: the AI plane consumes the small `api-lead` bucket M1 produces, never the raw wall.

## Global Constraints

_Every task's requirements implicitly include these (from CLAUDE.md):_

- **Deterministic, zero tokens in the scan path.** Same inputs → byte-identical output. No wall-clock in logic. `host_reputation.yaml` is loaded from disk; nothing is fetched at scan time.
- **"Cannot see" ≠ "clean", strengthened.** The `_IGNORE` set is *silently dropped* today. M1 must **keep and count** those hosts (bucketed + collapsed), never hide them. Nothing vanishes; everything is classed and countable.
- **Never invent a date.** M1 adds *no* dates and *no* vendor classifications — `hostClass` is orthogonal to `classified`/`vendor`. A catalogued vendor is still `classified:true`; `hostClass` only triages the *rest*.
- **The catalog is data, reviewed.** New reputation/template entries carry a `source:` and enter via review (same discipline as `vendors.yaml`). No live fetch.
- **Prove a guard against its bug.** The mls-mapper incident becomes a regression fixture; the triage test must be shown to FAIL on the pre-M1 behavior (flat wall) before the fix.
- **`verify` is the only correctness claim.** Extend it; a green `verify` must still mean drift.json/drift.md/dashboard.html agree, now including `hostClass`.
- Runtime deps stay **stdlib + PyYAML**. `verify.check_accessor_coverage` tracks loop vars `a|e|p|cv|row` — **any new cockpit `v-for` must use other names.**

---

## File Structure

- **Create** `agent/host_reputation.yaml` — reviewed reputation catalog. Buckets → sourced host lists. Seeded from the current `_IGNORE` + a pinned public tracker/CDN list.
- **Create** `agent/lib/host_class.py` — the classifier. Pure functions; no I/O beyond loading the YAML once.
- **Modify** `agent/lib/classify_url.py` — stop the silent `_IGNORE` drop; expose the ignore set to `host_class` as the `boilerplate`/`asset-cdn` seed instead of a delete.
- **Modify** `agent/lib/endpoints.py` — attach `hostClass` to each endpoint record (`endpoints.py:101`), passing a call-context signal.
- **Modify** `agent/lib/dashboard_render.py` — carry `hostClass` into the drift.json projection (`_endpoints_of`, ~line 64) and add per-bucket `counts`.
- **Modify** `agent/assets/dashboard.template.html` + `agent/assets/dashboard.app.js` + `agent/assets/dashboard.css` — group the unclassified list by `hostClass`.
- **Modify** `agent/lib/verify.py` — invariant: every endpoint has a valid `hostClass`; bucket counts match the payload.
- **Create** `tests/test_host_class.py` — classifier unit tests.
- **Create** `tests/fixtures/mls_incident/` — the regression fixture (a Metronic-style demo page, a `wa.me`/tiktok social block, a minified bundle header, and ONE real cURL API call).
- **Create** `tests/test_triage_incident.py` — the incident regression (proves the wall becomes a triaged list).

**hostClass vocabulary (closed set):** `api` (catalogued vendor) · `api-lead` (uncatalogued but API-shaped) · `social-widget` · `asset-cdn` · `analytics` · `vendored-lib` · `boilerplate` (schemas/doc hosts — the old `_IGNORE`) · `unclassified` (genuine residue). Ties resolve toward `unclassified`, never toward hiding.

---

## Task 1: The reputation catalog + classifier (`host_class.py`)

**Files:**
- Create: `agent/host_reputation.yaml`
- Create: `agent/lib/host_class.py`
- Test: `tests/test_host_class.py`

**Interfaces:**
- Produces: `host_class.classify(host: str, *, url: str | None = None, in_call: bool = False, file_ext: str | None = None) -> str` — returns one of the 8 `hostClass` values. `in_call` = the URL was matched inside an HTTP-client call context (vs. an href/src/CSS `url()`); `file_ext` = the source file's extension (`.css`/`.html` bias toward asset/widget).
- Consumes: `agent/host_reputation.yaml` loaded once (module-level cache), same load pattern as `catalog_overlay.load_list`.

- [ ] **Step 1: Write the failing test** — `tests/test_host_class.py`

```python
from agent.lib import host_class as hc

def test_reputation_beats_heuristics():
    assert hc.classify("connect.facebook.net") == "analytics"      # tracker list
    assert hc.classify("fonts.googleapis.com") == "asset-cdn"        # from old _IGNORE
    assert hc.classify("static.hotjar.com") == "analytics"

def test_social_share_grammar():
    assert hc.classify("wa.me", url="https://wa.me/15551234") == "social-widget"
    assert hc.classify("x.com", url="https://x.com/intent/tweet?text=x") == "social-widget"
    assert hc.classify("pinterest.com", url="https://pinterest.com/pin/create/button/") == "social-widget"

def test_api_shape_in_call_context_is_a_lead():
    # api. label / versioned path / inside an HTTP-client call -> a real lead, not noise
    assert hc.classify("api.greatschools.org", url="https://api.greatschools.org/v2/schools",
                       in_call=True) == "api-lead"

def test_asset_by_extension_or_path():
    assert hc.classify("images.unsplash.com", url="https://images.unsplash.com/photo-1.jpg") == "asset-cdn"
    assert hc.classify("cdn.example.com", file_ext=".css") == "asset-cdn"

def test_unknown_with_no_signal_is_unclassified_not_hidden():
    assert hc.classify("api-gateway.internal.acme.io") in ("api-lead", "unclassified")
    assert hc.classify("weird-host.example") == "unclassified"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_host_class.py -q`
Expected: FAIL — `ModuleNotFoundError: agent.lib.host_class`.

- [ ] **Step 3: Write `agent/host_reputation.yaml`** — reviewed data, each list sourced.

```yaml
# Deterministic host reputation — used ONLY to triage UNCATALOGUED hosts into visible buckets so
# the cockpit can rank real API leads above noise. NEVER affects `classified`/`vendor`/dates.
# Each list carries provenance; entries enter via review (same discipline as vendors.yaml).
# Seeded from: (1) the former classify_url._IGNORE set (was silently dropped — now visible);
#              (2) a PINNED snapshot of public tracker/CDN lists (source + date below). No live fetch.
meta:
  trackerSource: "DuckDuckGo Tracker Radar (pinned snapshot 2026-08-10) — CC-BY-SA"   # verify license at build
analytics:        # trackers / tag managers / session recorders
  - connect.facebook.net
  - static.hotjar.com
  - google-analytics.com
  - googletagmanager.com
asset-cdn:        # fonts, images, stock photos, JS/CSS CDNs
  - fonts.googleapis.com
  - fonts.gstatic.com
  - images.unsplash.com
  - pexels.com
  - cdnjs.cloudflare.com
  - jsdelivr.net
  - unpkg.com
social-widget:    # share links / embeds / follow buttons (host-level; grammar also matched in code)
  - wa.me
  - pinterest.com
  - tiktok.com
  - x.com
  - twitter.com
  - facebook.com
  - instagram.com
  - linkedin.com
vendored-lib:     # a UI kit / library talking about itself in its own docs/comments
  - keenthemes.com
  - momentjs.com
boilerplate:      # schema/doc hosts that are never integrations
  - w3.org
  - schema.org
  - www.sitemaps.org
  - localhost
```

- [ ] **Step 4: Write `agent/lib/host_class.py`**

```python
"""Deterministic triage of UNCATALOGUED hosts into a visible bucket (hostClass). Orthogonal to
vendor classification: it never sets `classified`/`vendor`/a date — it only sorts the residue so
real API leads rank above icons/CDNs/analytics. Reputation catalog (reviewed data) first, then
URL-shape + call-context heuristics; ties resolve to `unclassified`, never to hiding a host."""
from __future__ import annotations
import os
import re
import yaml

_REPUTATION_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "host_reputation.yaml")
_CACHE: dict | None = None

# share-URL grammars (host-independent): these paths ARE the button, not an API call
_SHARE_PATHS = re.compile(r"/(intent/|share|pin/create|sharer|dialog/)", re.I)
_API_LABEL = re.compile(r"(^|\.)api(\.|-|$)", re.I)
_API_PATH = re.compile(r"/(v[0-9]+|rest|graphql|oauth|api)(/|$)", re.I)
_ASSET_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|woff2?|ttf|css|js|ico|mp4)(\?|$)", re.I)
_ASSET_FILE_EXTS = {".css", ".scss", ".html", ".htm"}


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(_REPUTATION_FILE, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        # host -> bucket, longest-suffix wins; skip the `meta` block
        table = {}
        for bucket, hosts in doc.items():
            if bucket == "meta" or not isinstance(hosts, list):
                continue
            for h in hosts:
                table[h.lower()] = bucket
        _CACHE = table
    return _CACHE


def _reputation(host: str) -> str | None:
    table = _load()
    host = (host or "").lower()
    # exact + registrable-suffix match (mirrors classify_url's suffix rule)
    while host:
        if host in table:
            return table[host]
        host = host.split(".", 1)[1] if "." in host else ""
    return None


def classify(host: str, *, url: str | None = None, in_call: bool = False,
             file_ext: str | None = None) -> str:
    """Return the hostClass for an UNCATALOGUED host. (Catalogued vendors are handled upstream and
    always get `api` — this is never called for them.)"""
    rep = _reputation(host)
    if rep:
        return rep
    u = url or ""
    if _SHARE_PATHS.search(u):
        return "social-widget"
    if (file_ext or "").lower() in _ASSET_FILE_EXTS or _ASSET_EXT.search(u):
        return "asset-cdn"
    if in_call and (_API_LABEL.search(host or "") or _API_PATH.search(u)):
        return "api-lead"
    # an api-shaped host even without a proven call context is still worth surfacing as a lead
    if _API_LABEL.search(host or "") and _API_PATH.search(u):
        return "api-lead"
    return "unclassified"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_host_class.py -q`
Expected: PASS (5 tests). If `test_api_shape...` fails, confirm `in_call` path + `_API_LABEL` on `api.greatschools.org`.

- [ ] **Step 6: Commit**

```bash
git add agent/host_reputation.yaml agent/lib/host_class.py tests/test_host_class.py
git commit -m "feat(triage): deterministic host-class classifier + reviewed reputation catalog"
```

---

## Task 2: Attach `hostClass` to endpoint records (`endpoints.py`)

**Files:**
- Modify: `agent/lib/endpoints.py` (the record built at ~`endpoints.py:101`)
- Test: `tests/test_endpoints.py` (extend)

**Interfaces:**
- Consumes: `host_class.classify(...)`.
- Produces: every endpoint dict gains `"hostClass": str`. Rule: `classified` (catalogued vendor) ⇒ `"api"`; else `host_class.classify(host, url=example, in_call=<matched in a sink/url call context>, file_ext=<ext of first file>)`.

- [ ] **Step 1: Write the failing test** (extend `tests/test_endpoints.py`)

```python
from agent.lib.host_class import classify  # noqa (import proves availability)

def test_endpoints_carry_hostclass(tmp_path):
    _write(tmp_path, "a.php", 'x\n"https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')
    _write(tmp_path, "b.html", '<a href="https://wa.me/15551234">chat</a>\n')
    _write(tmp_path, "c.php", '$r = $client->get("https://api.greatschools.org/v2/schools");\n')
    ms = [_url("a.php", 2), _url("b.html", 1), _url("c.php", 1)]
    out = scan_endpoints(ms, str(tmp_path), _VENDORS)   # _VENDORS includes Amazon SP-API
    by = {e["domain"]: e["hostClass"] for e in out["endpoints"]}
    assert by["sellingpartnerapi-na.amazon.com"] == "api"       # catalogued vendor
    assert by["wa.me"] == "social-widget"                        # share link
    assert by["api.greatschools.org"] == "api-lead"             # api-shaped, uncatalogued
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_endpoints.py::test_endpoints_carry_hostclass -q`
Expected: FAIL — `KeyError: 'hostClass'`.

- [ ] **Step 3: Implement** — in `endpoints.py`, at the record construction (`endpoints.py:101`), add the field. The call-context signal: a URL match with `kind == "url"` found on the same line as a sink, OR the record already has a recognized sink; the file extension is `os.path.splitext(first_file)[1]`. Import `host_class` at top.

```python
# in scan_endpoints, when building `rec` (endpoints.py:101):
rec = {"vendor": vendor, "domain": host, "version": version, "techKey": techKey,
       "operation": operation, "apiPath": api_path,
       ...
       "example": (example or host).rstrip("\"';,)"), "file_count": 0, "files": [],
       "classified": bool(techKey)}
rec["hostClass"] = "api" if rec["classified"] else host_class.classify(
    host, url=rec["example"], in_call=_looks_like_call(m), file_ext=_ext_of(loc))
```

Add two small helpers near the top of `scan_endpoints` (keep them local, deterministic):

```python
def _ext_of(loc):            # "src/x.php:12" -> ".php"
    return os.path.splitext(loc.split(":")[0])[1].lower()
def _looks_like_call(m):     # url matched inside an http-client call vs an href/src/css url()
    text = (m.get("text") or "")
    return bool(re.search(r"(curl_|->(get|post|request)|Http::|fetch\(|axios|GuzzleHttp|client->)", text))
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/test_endpoints.py -q`
Expected: PASS. Existing endpoint tests unaffected (new field is additive).

- [ ] **Step 5: Commit** — `git commit -am "feat(triage): endpoints carry hostClass (api for catalogued, triaged otherwise)"`

---

## Task 3: Stop silently dropping `_IGNORE` — keep + bucket (`classify_url.py`)

**Files:**
- Modify: `agent/lib/classify_url.py`
- Test: `tests/test_classify_url.py` (extend) — or wherever `_IGNORE` behavior is currently asserted (check `tests/test_endpoints.py::test_boilerplate_hosts_ignored`).

**Interfaces:** `_IGNORE` hosts must no longer be deleted from the endpoint stream; they flow through and receive a `hostClass` of `boilerplate`/`asset-cdn`/`analytics` via the reputation catalog (Task 1 seeded them). The count "N filtered boilerplate" becomes visible.

- [ ] **Step 1: Update the existing guard test to the new contract.** Find the test asserting boilerplate hosts are dropped (`test_boilerplate_hosts_ignored`) and change it: the host now **appears** as an endpoint with `hostClass="asset-cdn"` (or `boilerplate`), `classified=False`, rather than being absent. This is the intentional honesty change — document it in the test comment.

- [ ] **Step 2: Run it to verify it fails** (old code still drops the host).

- [ ] **Step 3: Implement** — remove the `_ignored(host)` early-drop from the endpoint path in `classify_url`/`endpoints`. Keep `_IGNORE` only as the seed already folded into `host_reputation.yaml` (Task 1). If `_IGNORE` is referenced elsewhere as a genuine "never a real host" filter (localhost, example.com in tests), keep a *minimal* hard-drop set (`localhost`, `127.0.0.1`, `example.com`, `example.org`) and comment why — everything else becomes a bucketed endpoint.

- [ ] **Step 4: Run the full endpoints + classify suites** — `pytest tests/test_endpoints.py tests/test_classify_url.py -q`. Expected: PASS. Watch for tests that assumed a dropped host; update to the bucketed contract.

- [ ] **Step 5: Commit** — `git commit -am "feat(triage): surface (bucket) formerly-hidden _IGNORE hosts — honesty over silent drop"`

---

## Task 4: Carry `hostClass` into drift.json + bucket counts (`dashboard_render.py`)

**Files:**
- Modify: `agent/lib/dashboard_render.py` (`_endpoints_of` ~line 64; `counts` ~line 143)
- Test: `tests/test_dashboard_render.py` (extend)

- [ ] **Step 1: Failing test** — assert `drift.json` endpoints carry `hostClass`, and `counts` gains a `hostClasses` breakdown.

```python
def test_projection_carries_hostclass_and_bucket_counts():
    data = _blob(render_dashboard(_inv_with_hosts(), _audit([]), "2026-08-10"))
    assert all("hostClass" in e for e in data["endpoints"])
    hc = data["counts"]["hostClasses"]                 # {api, api-lead, social-widget, ...}
    assert hc["api-lead"] >= 1 and hc["social-widget"] >= 1
    # the 'unknown' tile now means leads worth attention, not the noise floor
    assert data["counts"]["unknown"] == hc.get("api-lead", 0) + hc.get("unclassified", 0)
```

- [ ] **Step 2: Run → fail** (no `hostClass` in projection, no `hostClasses` count).

- [ ] **Step 3: Implement** — in `_endpoints_of` add `"hostClass": e.get("hostClass", "unclassified")` to the projected dict (line 64 block). In the `counts` block (line 143) add:

```python
from collections import Counter
_hc = Counter(e["hostClass"] for e in endpoints)
counts["hostClasses"] = dict(_hc)
counts["apis"]    = len({e["vendor"] for e in endpoints if e["classified"]})
counts["unknown"] = _hc.get("api-lead", 0) + _hc.get("unclassified", 0)   # attention-worthy only
```

- [ ] **Step 4: Run `pytest tests/test_dashboard_render.py -q`** → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(triage): project hostClass + per-bucket counts into drift.json"`

---

## Task 5: Group the unclassified list in the cockpit (assets)

**Files:**
- Modify: `agent/assets/dashboard.app.js`, `agent/assets/dashboard.template.html`, `agent/assets/dashboard.css`
- Test: `tests/test_verify.py` (accessor coverage over the new template)

**Interfaces:** In the "Unclassified endpoints" hero/list, render endpoints grouped by `hostClass`: **"Possible API integrations"** (`api-lead`) expanded on top; `social-widget` / `asset-cdn` / `analytics` / `vendored-lib` / `boilerplate` as **collapsed** `<details>` groups with counts. Loop vars must NOT be `a|e|p|cv|row` (use `grp`, `ep`).

- [ ] **Step 1:** Add an `app.js` computed `hostGroups` that buckets the current unclassified endpoints into an ordered list of `{cls, label, items, open}` (api-lead → open; noise → closed). Use loop var `ep` inside.
- [ ] **Step 2:** Template: replace the flat unclassified `v-for` with `v-for="grp in hostGroups"` → a `<details :open="grp.open">` per group, `v-for="ep in grp.items"` inside; each row shows `ep.domain`, `ep.example`, and (for api-lead) the `file:line`. Add a one-line group blurb ("buttons & share links, not API calls").
- [ ] **Step 3:** CSS: minimal styling for the grouped `<details>` (reuse `.grp`/`.count`).
- [ ] **Step 4: Run `pytest tests/test_verify.py -q`** — `check_accessor_coverage` must stay green (no `a.`/`e.`/`p.`/`cv.`/`row.` reads added). Expected: PASS.
- [ ] **Step 5: Render + verify a real state**: `./bin/drift-scan render --state <fixture-state>` then `./bin/drift-scan verify --state <fixture-state>` → green.
- [ ] **Step 6: Commit** — `git commit -am "feat(triage): cockpit groups unclassified endpoints by hostClass, leads on top"`

---

## Task 6: `verify` invariant — every endpoint classed, buckets agree

**Files:**
- Modify: `agent/lib/verify.py`
- Test: `tests/test_verify.py`

- [ ] **Step 1: Failing test** — a payload with an endpoint missing `hostClass` (or a bucket count that disagrees with the endpoints) must raise `Violation`. Prove it fails on the pre-invariant behavior.

```python
def test_hostclass_invariant_catches_missing_class():
    payload = _payload_with_endpoint(hostClass=None)     # simulate a dropped field
    with pytest.raises(verify.Violation):
        verify.check_host_classes(payload)
```

- [ ] **Step 2: Run → fail** (`check_host_classes` doesn't exist).
- [ ] **Step 3: Implement `check_host_classes(payload)`** in `verify.py`: every `endpoints[].hostClass` is in the closed vocab; `counts.hostClasses` equals a recount of `endpoints`; `counts.unknown == api-lead + unclassified`. Register it in `verify_payload`.
- [ ] **Step 4: Run `pytest tests/test_verify.py -q`** → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(verify): hostClass invariant — every endpoint triaged, buckets agree"`

---

## Task 7: The mls-mapper incident regression fixture (prove-a-guard)

**Files:**
- Create: `tests/fixtures/mls_incident/` — `index.html` (Metronic-style demo: `wa.me`, `tiktok.com`, `pinterest.com` social block + `images.unsplash.com` `<img>`), `vendor/moment.min.js` (one-line header comment mentioning `momentjs.com`), `app/importer.php` (ONE real cURL to `https://api.greatschools.org/v2/schools`).
- Create: `tests/test_triage_incident.py`

- [ ] **Step 1: Write the fixture files** (small, representative — the four failure modes from the incident: social widget, asset CDN, vendored-lib header, one real API call).
- [ ] **Step 2: Write the failing test** — scan the fixture, assert the shape of the triage:

```python
def test_incident_becomes_triaged_not_a_wall(tmp_path):
    state = _scan(tmp_path, "tests/fixtures/mls_incident")   # helper runs the real pipeline
    hc = state["counts"]["hostClasses"]
    leads = [e for e in state["endpoints"] if e["hostClass"] == "api-lead"]
    assert [e["domain"] for e in leads] == ["api.greatschools.org"]   # the ONE real lead surfaces
    assert hc.get("social-widget", 0) >= 2                             # wa.me, tiktok, pinterest
    assert hc.get("asset-cdn", 0) >= 1                                 # unsplash
    # the attention count is 1, not "a wall" — the incident, inverted
    assert state["counts"]["unknown"] == len(leads)
```

- [ ] **Step 3: Run → confirm it PASSES with M1** and FAILS on pre-M1 (checkout `master`, run, observe the flat-unknown behavior — document the before/after in the test docstring; this is the principle-5 proof).
- [ ] **Step 4: Full suite** — `.venv/bin/python -m pytest -q`. Expected: all green (existing + new).
- [ ] **Step 5: Commit** — `git commit -m "test(triage): mls-mapper incident regression — wall of unknowns becomes 1 ranked lead"`

---

## Self-Review

- **Spec coverage:** Fable's M1 = (a) `hostClass` taxonomy [Tasks 1–2,4], (b) reputation catalog folding in the hidden `_IGNORE` [Tasks 1,3], (c) shape/context heuristics [Task 1], (d) grouped cockpit with leads-on-top [Task 5], (e) `verify` extension [Task 6], (f) the incident as a fixture [Task 7]. Covered.
- **Honesty principle:** Task 3 explicitly converts the silent drop into a visible bucket — strengthens "cannot-see ≠ clean" rather than weakening it. ✓
- **Moat intact:** `hostClass` never touches `classified`/`vendor`/dates (Global Constraints + Task 2 rule). The certified tier is unchanged; only the *residue* is triaged. ✓
- **Determinism:** reputation is disk-loaded, pinned; no fetch; classifier is pure. `verify` still byte-checks. ✓
- **Type consistency:** `hostClass` is one closed string set used identically in `endpoints.py` (write), `dashboard_render.py` (project + count), `verify.py` (check), and the cockpit (group). No name drift.
- **Accessor-coverage trap:** Task 5 flagged to use `grp`/`ep`, never `a|e|p|cv|row`.
- **Not in scope (deferred, correctly):** M2 scan-scope guardrail, M3 coverage-receipt, and the AI Recon/Shaper agents — each its own plan after M1.

## Execution Handoff

Recommended: **superpowers:subagent-driven-development** — 7 well-isolated tasks, each with its own test cycle and a clean reviewer gate. Branch `feat/triage-first` (already created off the canonical clean history). Each task ends green and independently shippable.

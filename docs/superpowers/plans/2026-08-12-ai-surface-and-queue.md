# One AI Surface, and a Queue That Means Something — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `queued` contain only genuinely un-researched third-party APIs, and collapse the three AI surfaces into the dashboard's existing AI Frontier tab with an executable firewall guarding the certified data.

**Architecture:** Two independent halves. The queue half extends the existing deterministic classifier (`host_class.classify` + `host_reputation.yaml`) and adds one new module that *derives* a client's own domains from the repo being scanned. The AI half is mostly wiring: `dashboard_render.render_payload` **already** accepts `adhoc=`/`leads=` and emits `adhoc-data`/`leads-data` blobs — the callers, the front-end consumer for leads, and the producer for `leads.json` are what's missing. Then the two side-car HTML renderers are deleted and `verify` gains the firewall invariant that file-separation used to provide for free.

**Tech Stack:** Python 3.11+ (stdlib + PyYAML only at runtime), pytest, vanilla Vue 3 in `agent/assets/dashboard.app.js`, YAML catalogs under `agent/`.

## Global Constraints

- **Runtime dependencies are stdlib + PyYAML only.** `jsonschema` is test-only. Never add a runtime import.
- **Deterministic, zero LLM tokens in the scan path.** Same inputs → byte-identical output. No `Date.now()`, no wall-clock reads in logic; `now` is always passed in.
- **Never invent a date.** No task here introduces a date claim. `leads.json` entries carry the tri-state `retired` (`"yes"|"no"|"unknown"`) and **never** a date.
- **Prove every guard against its bug.** Each test must be shown to FAIL before its fix lands. A step that says "run it and watch it fail" is not optional.
- **No client hostname enters the public tree.** `agent/host_reputation.yaml` and `agent/vendors.yaml` ship publicly. Client infrastructure is derived at scan time, never catalogued.
- **"Cannot see" ≠ "clean".** Hosts leaving `queued` must remain visible under Detected/Assets. Nothing is deleted from the inventory.
- **Test command:** `.venv/bin/python -m pytest -q` from the repo root. Baseline at plan time: **887 passed, 5 skipped**.
- **hostClass values must stay inside `host_class.VOCAB`** — `verify.check_host_classes` enforces the closed vocabulary and will fail the build otherwise.

## Spec deviation (decided during planning, carry it forward)

The spec said reserved-TLD placeholders would be "classified `boilerplate`". The codebase already has a distinct, deliberate mechanism for placeholders: `classify_url.is_nonhost()` **drops** them, and its `_PLACEHOLDER` tuple already contains `example.com`/`test.com`/`localhost`. Task 2 therefore extends `_PLACEHOLDER` (a drop) for the reserved TLDs `.test`/`.example`/`.invalid`/`.localhost`, which are *by definition* never real, and puts `acme.com` — a real registrable domain used only by convention — in the reputation catalog as `boilerplate` instead. This follows the existing pattern rather than adding a second one.

---

### Task 1: Reputation catalog — bucket the docs, social and asset hosts

**Files:**
- Modify: `agent/host_reputation.yaml` (append to the existing `social-widget`, `asset-cdn` and `boilerplate` lists)
- Test: `tests/test_host_class.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing new in code. `host_class.classify(host)` returns `"boilerplate"`, `"social-widget"` or `"asset-cdn"` for the added hosts, which makes `dashboard_render._coverage()` return `"na"` for them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_host_class.py`:

```python
import pytest
from agent.lib import host_class


# Each host below sat in `queued` on a real Laravel scan, described as "an API service we haven't
# researched yet". None of them is an API service. rfc-editor.org is the tell: the same host was
# ALREADY excluded as boilerplate through another path, so the queue and the exclusion list
# disagreed with each other about the same domain.
@pytest.mark.parametrize("host,expected", [
    ("spdx.org", "boilerplate"),
    ("spec.openapis.org", "boilerplate"),
    ("www.rfc-editor.org", "boilerplate"),
    ("reactjs.org", "boilerplate"),
    ("redux.js.org", "boilerplate"),
    ("vladimirgorej.com", "boilerplate"),
    ("acme.com", "boilerplate"),
    ("fb.me", "social-widget"),
    ("www.snapchat.com", "social-widget"),
    ("www.threads.net", "social-widget"),
    ("soundcloud.com", "social-widget"),
    ("get.adobe.com", "asset-cdn"),
])
def test_queue_noise_is_bucketed_not_queued(host, expected):
    assert host_class.classify(host) == expected


@pytest.mark.parametrize("host", [
    "spdx.org", "www.rfc-editor.org", "fb.me", "soundcloud.com", "get.adobe.com", "acme.com",
])
def test_bucketed_hosts_are_not_integrations(host):
    """`is_integration` False is what keeps them out of the audit backlog — the queue count."""
    assert not host_class.is_integration(host_class.classify(host))
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_host_class.py -q -k queue_noise`
Expected: FAIL — every case returns `"unclassified"` instead of its bucket.

- [ ] **Step 3: Add the entries to the catalog**

In `agent/host_reputation.yaml`, append to the existing `social-widget:` list:

```yaml
  - fb.me                 # Facebook's short-link host — a share/profile link, never an API
  - snapchat.com
  - threads.net
  - soundcloud.com        # embedded player/profile links; SoundCloud's real API is api.soundcloud.com,
                          # which the `api.` host-label rule still catches as a lead
```

Append to the existing `asset-cdn:` list:

```yaml
  - get.adobe.com         # the "Get Acrobat Reader" download badge — an outbound link, not a service
```

Append to the existing `boilerplate:` list:

```yaml
  # ── spec / documentation hosts. These reached the QUEUE on a real scan and were described as
  # "an API service we haven't researched yet"; rfc-editor.org was already excluded elsewhere,
  # so the tool disagreed with itself about the same domain.
  - spdx.org              # SPDX licence identifiers, cited in SBOM/licence headers
  - spec.openapis.org     # OpenAPI spec URLs in swagger annotations
  - rfc-editor.org        # RFC citations, same family as the already-listed ietf.org
  - reactjs.org           # framework docs linked from scaffolding comments
  - redux.js.org
  - vladimirgorej.com     # author homepage in a vendored swagger-client's headers
  - acme.com              # placeholder org name in generated docs/fixtures. NOT dropped via
                          # classify_url._PLACEHOLDER: it is a REAL registrable domain, so a
                          # genuine call to it must stay visible rather than silently vanish.
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_host_class.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/host_reputation.yaml tests/test_host_class.py
git commit -m "fix(host-class): bucket spec/social/asset hosts that were sitting in the research queue"
```

---

### Task 2: Reserved-TLD placeholders stop entering the scan

**Files:**
- Modify: `agent/lib/classify_url.py` (the `_PLACEHOLDER` tuple, around line 69)
- Test: `tests/test_classify_url.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `classify_url.is_nonhost(host) -> bool` now returns `True` for RFC 2606 / RFC 6761 reserved names. Signature unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_classify_url.py`:

```python
from agent.lib import classify_url


# RFC 2606 / RFC 6761 reserve these names precisely so they can never resolve to a real service.
# `cdn.example.test` reached the research queue on a real scan, where it read as a third-party CDN
# awaiting audit. A reserved name is the one case where dropping is honest rather than hiding:
# there is no service behind it to be blind to.
def test_reserved_tlds_are_not_hosts():
    for host in ("cdn.example.test", "api.foo.invalid", "svc.example", "thing.localhost",
                 "shop.example.com", "api.test.com"):
        assert classify_url.is_nonhost(host), host


def test_a_real_domain_that_merely_looks_like_a_placeholder_survives():
    """acme.com is a REAL registrable domain — it must stay visible and be typed by
    host_class (Task 1), never dropped here."""
    assert not classify_url.is_nonhost("acme.com")
    assert not classify_url.is_nonhost("testing-services.io")
    assert not classify_url.is_nonhost("api.exampletree.com")
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_classify_url.py -q -k reserved_tlds`
Expected: FAIL — `cdn.example.test`, `api.foo.invalid`, `svc.example` and `thing.localhost` all return `False`.

- [ ] **Step 3: Extend the placeholder set**

In `agent/lib/classify_url.py`, replace the `_PLACEHOLDER` definition:

```python
# Test/placeholder domains that are never a real third-party integration. The bare entries are
# RFC 2606 / RFC 6761 RESERVED names — the standard guarantees nothing resolves behind them, so
# dropping is honest here in a way it never is for a real domain. (A real domain used as a
# convention, like acme.com, goes to host_reputation.yaml as `boilerplate` instead: it stays
# visible, because a genuine call to it must not vanish.)
_PLACEHOLDER = ("example.com", "example.org", "example.net", "test.com", "localhost",
                "test", "example", "invalid")
```

The existing suffix match in `is_nonhost` — `h == s or h.endswith("." + s)` — makes each bare entry
match as a TLD, so `cdn.example.test` matches `test` and `thing.localhost` matches `localhost`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_classify_url.py -q`
Expected: PASS. Then run the full suite — `is_nonhost` is on the hot path for every scan:
`.venv/bin/python -m pytest -q` → expected 889+ passed, 5 skipped, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/classify_url.py tests/test_classify_url.py
git commit -m "fix(scan): treat RFC 2606/6761 reserved names as non-hosts"
```

---

### Task 3: `own_infra.py` — derive the client's own domains from the repo

**Files:**
- Create: `agent/lib/own_infra.py`
- Test: `tests/test_own_infra.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `own_infra.signals(repo_path: str = "", repo_id: str = "") -> dict` returning `{"tokens": set[str], "domains": set[str]}`
  - `own_infra.is_own(host: str, sig: dict) -> bool`
  Task 4 calls both.

- [ ] **Step 1: Write the failing test**

Create `tests/test_own_infra.py`:

```python
"""A client's own hostnames can never be catalogued — agent/host_reputation.yaml ships in a PUBLIC
repo — and cannot be pattern-guessed, because a `cdn.*` rule would claim a genuine CDN vendor. They
are derived from the repo being scanned.

The signals were chosen against a real repo, after the obvious ones were measured and REJECTED:
its .env.example had APP_URL=http://localhost and its composer.json name was the framework default
`laravel/laravel`. Config-derived inference produced nothing at all.
"""
from agent.lib import own_infra


def _sig():
    return own_infra.signals(repo_path="/srv/checkouts/promoteplus-crm",
                             repo_id="https://git.topsdemo.in/root/promoteplus-crm.git")


def test_repo_name_token_catches_the_clients_own_hosts():
    sig = _sig()
    assert sig["tokens"] == {"promoteplus"}          # `crm` is generic and too short
    for host in ("crm.promoteplus.ai", "promotepluscdn.com", "qa-promoteplus-idx.topsdemo.in"):
        assert own_infra.is_own(host, sig), host


def test_self_hosted_forge_domain_is_own_infra():
    sig = _sig()
    assert "topsdemo.in" in sig["domains"]
    assert own_infra.is_own("anything.topsdemo.in", sig)


def test_a_public_forge_is_never_treated_as_own_infra():
    """The decisive negative. A github.com remote would otherwise make the registrable domain
    `github.com` own-infra, silently suppressing every github.com host in every repo."""
    sig = own_infra.signals(repo_path="/srv/acme-shop",
                            repo_id="https://github.com/acme/acme-shop.git")
    assert sig["domains"] == set()
    assert not own_infra.is_own("api.github.com", sig)
    assert not own_infra.is_own("raw.githubusercontent.com", sig)


def test_real_vendor_hosts_are_never_claimed():
    sig = _sig()
    for host in ("api.justcall.io", "hooks.zapier.com", "api.mailgun.net",
                 "graph.microsoft.com", "api.openai.com"):
        assert not own_infra.is_own(host, sig), host


def test_short_and_generic_names_yield_no_token():
    """Failing toward SHOWN. A repo called `crm` or `laravel-api` produces no usable token, so its
    hosts stay queued rather than being suppressed by a 3-letter substring match."""
    assert own_infra.signals(repo_path="/srv/crm")["tokens"] == set()
    assert own_infra.signals(repo_path="/srv/laravel-api")["tokens"] == set()
    assert own_infra.signals(repo_path="/srv/web-portal")["tokens"] == set()


def test_no_signals_means_no_claims():
    sig = own_infra.signals()
    assert sig == {"tokens": set(), "domains": set()}
    assert not own_infra.is_own("crm.promoteplus.ai", sig)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_own_infra.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.lib.own_infra'`.

- [ ] **Step 3: Write the module**

Create `agent/lib/own_infra.py`:

```python
"""Derive the hosts that are the SCANNED REPO'S OWN infrastructure, from the repo itself.

Client hostnames cannot be catalogued: agent/host_reputation.yaml ships in a public repo, so a
client's staging box must never be written into it. They also cannot be pattern-guessed — a
`cdn.*` / `qa-*` heuristic would claim a genuine third-party CDN, which is the false confidence
this tool exists to refuse. So they are DERIVED, per scan, from what the repo already tells us.

Two signals, both taken from the repo's own identity:

  token    the repo's name contributes a distinctive token (`promoteplus-crm` -> `promoteplus`),
           and a host containing it is that project's own box.
  domain   a SELF-HOSTED forge remote (git.acme.internal/...) names the organisation's own
           domain. Public forges are excluded — a github.com remote says nothing about who owns
           api.github.com.

Config-derived inference (APP_URL, composer/package name) was measured on a real repo and
rejected: APP_URL was `http://localhost` and the composer name was the framework default
`laravel/laravel`. A signal that real projects leave at default is not a signal.

Deterministic and pure: inputs in, set out. No filesystem, no network, no clock.
"""
from __future__ import annotations

import os
import re

# Tokens that identify no one — every second repo carries them.
_GENERIC = frozenset({
    "client", "server", "backend", "frontend", "service", "services", "common", "shared",
    "laravel", "symfony", "django", "rails", "express", "nextjs", "spring", "dotnet",
    "project", "website", "webapp", "portal", "platform", "system", "master", "public",
    "private", "internal", "staging", "production", "develop", "monorepo", "template",
})

# Shorter tokens collide with ordinary substrings of real vendor hosts (`api`, `crm`, `shop`).
# Six is the point at which an accidental match stops being plausible.
_MIN_TOKEN = 6

# A remote on one of these says nothing about who owns the forge's own hosts. Without this,
# a github.com remote would make `github.com` own-infra and suppress every github.com host.
_PUBLIC_FORGES = frozenset({
    "github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "sourceforge.net",
    "sr.ht", "dev.azure.com", "visualstudio.com", "gitee.com", "launchpad.net",
})

_REMOTE = re.compile(r"^(?:(?:https?|ssh|git)://)?(?:[^@/]+@)?([^/:]+)[/:](.+?)(?:\.git)?/?$")


def _tokens(name: str) -> set:
    return {t for t in re.split(r"[-_.]+", (name or "").lower())
            if len(t) >= _MIN_TOKEN and t.isalnum() and t not in _GENERIC}


def _registrable(host: str) -> str:
    labels = [l for l in (host or "").lower().split(".") if l]
    return ".".join(labels[-2:]) if len(labels) >= 2 else ""


def signals(repo_path: str = "", repo_id: str = "") -> dict:
    """{'tokens', 'domains'} — everything derivable about this repo's own identity.

    `repo_path` is the checkout directory; `repo_id` is the git remote (or the identity string
    `scope_edges.identity` normalises), either of which may be absent.
    """
    tokens = _tokens(os.path.basename((repo_path or "").rstrip("/")))
    domains: set = set()
    m = _REMOTE.match((repo_id or "").strip())
    if m:
        host, path = m.group(1), m.group(2)
        tokens |= _tokens(path.rstrip("/").split("/")[-1])
        reg = _registrable(host)
        if reg and reg not in _PUBLIC_FORGES:
            domains.add(reg)
    return {"tokens": tokens, "domains": domains}


def is_own(host: str, sig: dict) -> bool:
    """Is `host` this repo's own infrastructure? False on no signal — failing toward SHOWN."""
    h = (host or "").lower()
    if not h:
        return False
    if any(h == d or h.endswith("." + d) for d in sig.get("domains") or ()):
        return True
    return any(t in h for t in sig.get("tokens") or ())
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_own_infra.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/own_infra.py tests/test_own_infra.py
git commit -m "feat(scan): derive a repo's own infrastructure hosts from the repo itself"
```

---

### Task 4: Wire `own_infra` into the classifier

**Files:**
- Modify: `agent/lib/host_class.py` (the `classify` signature and body, lines 82-108)
- Modify: `agent/lib/endpoints.py` (build the signals once in `scan_endpoints`, pass at line 148)
- Test: `tests/test_host_class.py`

**Interfaces:**
- Consumes: `own_infra.signals()` / `own_infra.is_own()` from Task 3.
- Produces: `host_class.classify(host, *, url=None, in_call=False, file_ext=None, own=None) -> str`. The new `own` keyword takes the dict from `own_infra.signals()`; omitting it preserves today's behaviour exactly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_host_class.py`:

```python
from agent.lib import own_infra


def _sig():
    return own_infra.signals(repo_path="/srv/promoteplus-crm",
                             repo_id="https://git.topsdemo.in/root/promoteplus-crm.git")


def test_own_infra_wins_over_the_api_label_rule():
    """Ordering matters and is the whole point: `api.<client>.com` is the client's OWN API, not a
    third-party lead. The `api.` label rule runs early, so own-infra must run before it."""
    assert host_class.classify("api.promoteplus.ai", own=_sig()) == "own-infra"
    assert host_class.classify("crm.promoteplus.ai", own=_sig()) == "own-infra"
    assert host_class.classify("qa-promoteplus-idx.topsdemo.in", own=_sig()) == "own-infra"


def test_own_infra_never_claims_a_third_party():
    for host in ("api.justcall.io", "hooks.zapier.com", "graph.microsoft.com"):
        assert host_class.classify(host, own=_sig()) != "own-infra", host


def test_classify_without_signals_is_unchanged():
    """The `own` keyword is optional; every existing caller must behave identically without it."""
    assert host_class.classify("crm.promoteplus.ai") == "unclassified"
    assert host_class.classify("api.justcall.io") == "api-lead"
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_host_class.py -q -k own_infra`
Expected: FAIL with `TypeError: classify() got an unexpected keyword argument 'own'`.

- [ ] **Step 3: Add the parameter and the check**

In `agent/lib/host_class.py`, add the import at the top with the others:

```python
from agent.lib import own_infra
```

Then replace the `classify` signature and the first lines of its body:

```python
def classify(host: str, *, url: str | None = None, in_call: bool = False,
             file_ext: str | None = None, own: dict | None = None) -> str:
    """Return the hostClass for an UNCATALOGUED host (always a member of VOCAB).

    `in_call` — the URL was matched inside an HTTP-client call (vs. an href/src/CSS url()).
    `file_ext` — the source file's extension (a `.css`/`.scss` origin biases toward a static asset).
    `own` — this repo's own-infrastructure signals (agent.lib.own_infra.signals). Optional; absent
    means no host is claimed as own-infra, which is exactly the pre-existing behaviour.
    """
    host = host or ""
    if _OWN_CLOUD.search(host):
        return "own-infra"                 # your own cloud backend (Cognito, API GW, serverless…)
    # BEFORE the api-label rule on purpose: `api.<client>.com` is the client's OWN API, not a
    # third-party lead. A catalogued vendor never reaches here (endpoints.py sets `api` upstream),
    # so a client whose name collides with a vendor cannot suppress that vendor.
    if own and own_infra.is_own(host, own):
        return "own-infra"
    # an api. / -api. / api- host is a real API even UNDER a reputationed parent domain — so
```

Leave the rest of the function untouched.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.venv/bin/python -m pytest tests/test_host_class.py -q`
Expected: PASS.

- [ ] **Step 5: Pass the signals from the scanner**

In `agent/lib/endpoints.py`, add `own_infra` to the existing import on line 14:

```python
from agent.lib import classify_url, host_class, own_infra, scope_edges
```

In `scan_endpoints`, immediately after the existing `groups: dict = {}` line, build the signals once
per repo:

```python
    # This repo's own-infrastructure signals, derived once (pure; see agent/lib/own_infra.py).
    own_sig = own_infra.signals(repo_path=repo_root, repo_id=repo_id or "")
```

Then at line 148, pass it through:

```python
            rec["hostClass"] = "api" if rec["classified"] else host_class.classify(
                host, url=rec["example"], in_call=_looks_like_call(line), file_ext=_ext_of(rel),
                own=own_sig)
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. `verify.check_host_classes` enforces the closed vocabulary, and `own-infra` is
already a member of `VOCAB`, so no vocabulary change is needed.

- [ ] **Step 7: Commit**

```bash
git add agent/lib/host_class.py agent/lib/endpoints.py tests/test_host_class.py
git commit -m "feat(scan): classify the scanned repo's own hosts as own-infra"
```

---

### Task 5: Ten real vendors into the catalog

**Files:**
- Modify: `agent/vendors.yaml`
- Test: `tests/test_vendors_catalog.py` (create if absent)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: ten new vendor entries. Their endpoints become `classified: True`, so `hostClass` is `api` and `_coverage()` returns `tracked`. Their catalog verdict is `UNAUDITED` until somebody attests them — deliberately, since no retirement list has been checked.

- [ ] **Step 1: Write the failing test**

Create (or append to) `tests/test_vendors_catalog.py`:

```python
from agent.lib import classify_url, vendors as vendors_mod


def _vendors():
    return vendors_mod.load_vendors()


# Found by the AI cross-check plane and confirmed in code on a real repo: the scanner SAW these
# hosts but could not classify them, so they sat in `queued` and never reached the catalog layer.
# Detection is the gap here, not the retirement catalog.
def test_the_three_confirmed_integrations_classify():
    v = _vendors()
    assert classify_url.classify_host("api.justcall.io", v).vendor == "JustCall"
    assert classify_url.classify_host("hooks.zapier.com", v).vendor == "Zapier"
    assert classify_url.classify_host("login.microsoftonline.com", v).vendor == "Microsoft Identity"


# A dependency's published config enumerates these. Whether a code path selects them is a separate
# question from whether the code references them — classify them, then let the attestation layer
# say (honestly) that nobody has checked their retirement lists.
def test_the_ai_provider_hosts_classify():
    v = _vendors()
    for host, vendor in [("api.deepseek.com", "DeepSeek"), ("api.groq.com", "Groq"),
                         ("api.mistral.ai", "Mistral AI"), ("api.x.ai", "xAI"),
                         ("openrouter.ai", "OpenRouter"), ("api.elevenlabs.io", "ElevenLabs"),
                         ("api.voyageai.com", "Voyage AI")]:
        got = classify_url.classify_host(host, v)
        assert got is not None and got.vendor == vendor, host


def test_new_vendors_are_unaudited_not_silently_current():
    """Classifying a vendor must NOT imply its retirements are checked. These ten have no
    attestation, so the catalog verdict stays UNAUDITED — 0 findings for them is not 'clean'."""
    from agent.lib import catalog_coverage
    att = catalog_coverage.load_attestations()
    for vendor in ("JustCall", "Zapier", "Microsoft Identity", "DeepSeek", "Groq",
                   "Mistral AI", "xAI", "OpenRouter", "ElevenLabs", "Voyage AI"):
        assert catalog_coverage.verdict_for(vendor, att, "2026-08-12")[0] == "UNAUDITED"
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_vendors_catalog.py -q`
Expected: FAIL — `classify_host` returns `None` for every host.

If `vendors_mod.load_vendors()` is not the loader's name, run
`grep -n "^def load" agent/lib/vendors.py` and use the actual one; the rest of the test is unchanged.

- [ ] **Step 3: Add the entries**

Append to `agent/vendors.yaml`:

```yaml
# ── Communications / automation ────────────────────────────────────────────
# DETECTION ONLY — each host was observed in real code; no retirement list has been checked, so
# these are deliberately UNAUDITED (see agent/catalog_attestations.yaml). Naming the integration
# is the value; implying its versions are current would be the false-clean this tool refuses.
- { vendor: JustCall,           techKey: api:justcall,           domains: [justcall.io] }
- { vendor: Zapier,             techKey: api:zapier,             domains: [zapier.com] }
- { vendor: Microsoft Identity, techKey: api:microsoft-identity, domains: [login.microsoftonline.com, login.microsoft.com] }

# ── AI / LLM providers ─────────────────────────────────────────────────────
# Enumerated by a dependency's PUBLISHED config (a Laravel app ships the package's config file),
# so the code references them whether or not a code path selects one. Classified so they are named
# and countable; UNAUDITED because nobody has read their deprecation pages.
- { vendor: DeepSeek,           techKey: api:deepseek,           domains: [deepseek.com] }
- { vendor: Groq,               techKey: api:groq,               domains: [groq.com] }
- { vendor: Mistral AI,         techKey: api:mistral,            domains: [mistral.ai] }
- { vendor: xAI,                techKey: api:xai,                domains: [x.ai] }
- { vendor: OpenRouter,         techKey: api:openrouter,         domains: [openrouter.ai] }
- { vendor: ElevenLabs,         techKey: api:elevenlabs,         domains: [elevenlabs.io] }
- { vendor: Voyage AI,          techKey: api:voyageai,           domains: [voyageai.com] }
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_vendors_catalog.py -q`
Expected: PASS.

Then confirm `x.ai` did not collide with the already-catalogued `x.com` (social-widget):
`.venv/bin/python -c "from agent.lib import classify_url, vendors; v=vendors.load_vendors(); print(classify_url.classify_host('x.com', v))"`
Expected: `None` — `x.com` must NOT resolve to xAI. If it does, narrow the xAI domain to `api.x.ai`
and re-run.

- [ ] **Step 5: Run the full suite and commit**

```bash
.venv/bin/python -m pytest -q
git add agent/vendors.yaml tests/test_vendors_catalog.py
git commit -m "feat(catalog): classify ten detected-but-unnamed vendors (UNAUDITED, not clean)"
```

---

### Task 6: `leads` subcommand — produce `leads.json`

**Files:**
- Modify: `agent/cli.py` (replace `_cmd_probabilistic` at line 644; replace the parser at line 1440)
- Modify: `bin/drift-scan` (subcommand allowlist, line 93)
- Test: `tests/test_cli_leads.py` (create), `tests/test_cli_probabilistic.py` (delete)

**Interfaces:**
- Consumes: `agent.lib.probabilistic.compare` (existing, unchanged — it produced the agree / AI-only / tool-only tally and is kept).
- Produces: `leads.json`, a `drift-leads/v1` document:
  `{"schema": "drift-leads/v1", "checked": "<now>", "meta": {...}, "repos": [...], "tally": {"agree": int, "aiOnly": int, "toolOnly": int}}`.
  Tasks 7 and 8 read this file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_leads.py`:

```python
import json
from agent import cli


def _state(tmp_path):
    drift = {"endpoints": [{"repo": "r1", "vendor": "eBay", "classified": True,
                            "domain": "api.ebay.com", "files": ["a.php:1"]}]}
    (tmp_path / "drift.json").write_text(json.dumps(drift))
    ai = {"meta": {"reposRead": 1, "tokens": 5}, "repos": [{"repo": "r1", "summary": "s",
          "integrations": [{"vendor": "Kogan", "host": "api.kgn.io", "endpoint": "x",
                            "file": "k.php", "line": "9", "retired": "unknown"}]}]}
    (tmp_path / "ai.json").write_text(json.dumps(ai))
    return str(tmp_path / "ai.json")


def test_leads_writes_a_versioned_document(tmp_path):
    ai = _state(tmp_path)
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai, "--now", "2026-08-12"])
    assert rc == 0
    doc = json.loads((tmp_path / "leads.json").read_text())
    assert doc["schema"] == "drift-leads/v1"
    assert doc["checked"] == "2026-08-12"
    assert doc["repos"][0]["integrations"][0]["vendor"] == "Kogan"
    assert set(doc["tally"]) == {"agree", "aiOnly", "toolOnly"}


def test_leads_writes_no_side_car_html(tmp_path):
    """The whole point of the change: one surface. A second dashboard must not reappear."""
    ai = _state(tmp_path)
    cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai, "--now", "2026-08-12"])
    assert not (tmp_path / "probabilistic.html").exists()


def test_leads_refuses_a_date_in_a_lead(tmp_path):
    """A date is a CERTIFIED-tier claim. A lead may only say WHETHER something is retired —
    `retired` is the tri-state yes/no/unknown. Letting a date through here would route an
    ungated model-produced date into the same document the certified data lives in."""
    _state(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "2026-01-01"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2
    assert not (tmp_path / "leads.json").exists()


def test_leads_refuses_a_non_tristate_retired(tmp_path):
    _state(tmp_path)
    bad = tmp_path / "bad2.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "probably"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2


def test_leads_keeps_the_existing_refusals(tmp_path):
    _state(tmp_path)
    (tmp_path / "malformed.json").write_text('{"not": "the shape"}')
    assert cli.main(["leads", "--state", str(tmp_path),
                     "--ai-results", str(tmp_path / "malformed.json"), "--now", "2026-08-12"]) == 2
    (tmp_path / "norepo.json").write_text(json.dumps({"meta": {}, "repos": [{"integrations": []}]}))
    assert cli.main(["leads", "--state", str(tmp_path),
                     "--ai-results", str(tmp_path / "norepo.json"), "--now", "2026-08-12"]) == 2


def test_leads_needs_a_prior_scan(tmp_path):
    ai = tmp_path / "ai.json"
    ai.write_text('{"meta":{},"repos":[]}')
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(ai),
                     "--now", "2026-08-12"]) == 2
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_cli_leads.py -q`
Expected: FAIL — argparse rejects the unknown `leads` subcommand.

- [ ] **Step 3: Replace `_cmd_probabilistic` with `_cmd_leads`**

In `agent/cli.py`, replace the whole `_cmd_probabilistic` function (starting line 644) with:

```python
_TRISTATE = ("yes", "no", "unknown")
_DATEISH = re.compile(r"\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}")


def _cmd_leads(args) -> int:
    """Validate an AI cross-check pass into <state>/leads.json (drift-leads/v1).

    Replaces the old `probabilistic` subcommand and its side-car HTML: leads now ride in the
    dashboard's AI Frontier tab as their own blob. Pure + deterministic: no network, no tokens.
    Refuses malformed input, and refuses a DATE in a lead — a date is a certified-tier claim, and
    a lead may only say WHETHER (`retired` is the tri-state yes/no/unknown).
    """
    from agent.lib.probabilistic import compare
    drift_path = os.path.join(args.state, "drift.json")
    try:
        with open(drift_path, encoding="utf-8") as fh:
            drift = json.load(fh)
    except (OSError, json.JSONDecodeError):
        print(f"leads: no/unreadable drift.json in {args.state} — run a scan first", file=sys.stderr)
        return 2
    try:
        with open(args.ai_results, encoding="utf-8") as fh:
            ai = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"leads: cannot read --ai-results ({exc})", file=sys.stderr)
        return 2
    if not isinstance(ai, dict) or not isinstance(ai.get("repos"), list):
        print("leads: --ai-results malformed — expected {meta, repos:[...]}", file=sys.stderr)
        return 2
    problems = []
    for entry in ai["repos"]:
        if not isinstance(entry, dict) or "repo" not in entry:
            print('leads: --ai-results malformed — every repos[] entry needs a "repo" key',
                  file=sys.stderr)
            return 2
        for i in entry.get("integrations") or []:
            r = str((i or {}).get("retired", "")).strip().lower()
            host = (i or {}).get("host") or (i or {}).get("vendor") or "?"
            if _DATEISH.search(r):
                problems.append(f"{host}: 'retired' carries a date ({r!r}) — a lead says WHETHER, "
                                f"never WHEN; a dated claim must go through the absorb gate")
            elif r not in _TRISTATE:
                problems.append(f"{host}: 'retired' is {r!r}, not one of yes/no/unknown")
    if problems:
        print("leads: REFUSED — a lead may not carry a certified-tier claim:", file=sys.stderr)
        for p in problems:
            print("  •", p, file=sys.stderr)
        return 2
    tally = compare(drift, ai)
    doc = {"schema": "drift-leads/v1", "checked": args.now,
           "meta": ai.get("meta") or {}, "repos": ai["repos"], "tally": tally}
    out = os.path.join(args.state, "leads.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    print(f"✓ leads recorded: {tally['agree']} agree · {tally['aiOnly']} AI-only · "
          f"{tally['toolOnly']} tool-only — written to {out}")
    print("  re-run `render`/`run` on this state to surface them in the AI Frontier tab.")
    return 0
```

Confirm `re` is already imported at the top of `agent/cli.py`; add `import re` if not.

Check `compare`'s return shape first — run
`.venv/bin/python -c "import inspect; from agent.lib import probabilistic; print(inspect.getsource(probabilistic.compare))"`.
If it does not already return a dict with `agree`/`aiOnly`/`toolOnly`, adapt the `tally = ...` line
to build exactly that dict from what it does return. Do not change `compare` itself — its logic is
what produced the correct 2 / 7 / 3 tally on the reference repo.

- [ ] **Step 4: Re-register the subcommand**

In `agent/cli.py`, replace the `probabilistic` parser block at line 1440:

```python
    lds = sub.add_parser("leads")           # AI cross-check -> leads.json (AI Frontier tab)
    lds.add_argument("--state", required=True)
    lds.add_argument("--ai-results", required=True)
    lds.add_argument("--now", required=True)
    lds.set_defaults(func=_cmd_leads)
```

Keep the flag names identical to the old parser so existing callers need only the verb changed.

In `bin/drift-scan` line 93, replace `probabilistic` with `leads` in the case list.

- [ ] **Step 5: Delete the superseded tests and run**

```bash
git rm tests/test_cli_probabilistic.py
.venv/bin/python -m pytest tests/test_cli_leads.py -q
```

Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add agent/cli.py bin/drift-scan tests/test_cli_leads.py
git commit -m "feat(cli): leads.json replaces the probabilistic side-car report"
```

---

### Task 7: `run` embeds the adhoc and leads blobs

**Files:**
- Modify: `agent/run.py` (lines 69-77)
- Test: `tests/test_run_ai_blobs.py` (create)

**Interfaces:**
- Consumes: `leads.json` from Task 6; `adhoc.json` from the existing `adhoc-report`.
- Produces: `dashboard.html` containing `adhoc-data` and/or `leads-data` blobs when those files exist in the state dir. `render_payload` already accepts both keywords — this only supplies them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_ai_blobs.py`:

```python
import json
from agent.lib.dashboard_render import render_payload


def _payload():
    return {"counts": {"fixes": 0}, "generated": "2026-08-12", "endpoints": [], "findings": [],
            "catalog": [], "coverageGrades": [], "actions": [], "notes": []}


def test_absent_blobs_hide_the_tier_rather_than_showing_zero():
    """'Cannot see' != 'clean', extended to the AI tiers: no pass ran means the tier is HIDDEN,
    not rendered as a confident 0."""
    html = render_payload(_payload(), "2026-08-12")
    assert 'id="leads-data"' not in html
    assert 'id="adhoc-data"' not in html


def test_blobs_are_embedded_when_present():
    html = render_payload(_payload(), "2026-08-12",
                          adhoc={"schema": "drift-adhoc/v1", "claims": []},
                          leads={"schema": "drift-leads/v1", "repos": []})
    assert 'id="leads-data"' in html and 'id="adhoc-data"' in html


def test_the_certified_blob_is_byte_identical_with_and_without_ai_blobs():
    """The firewall, at the rendering layer: adding an AI tier must not perturb `drift-data` by a
    single byte. verify.check_blob_matches_payload is id-anchored, and this is what keeps that true.
    """
    import re
    def certified(html):
        m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>', html,
                      re.S)
        return m.group(1)
    plain = render_payload(_payload(), "2026-08-12")
    withai = render_payload(_payload(), "2026-08-12",
                            adhoc={"schema": "drift-adhoc/v1"}, leads={"schema": "drift-leads/v1"})
    assert certified(plain) == certified(withai)
```

- [ ] **Step 2: Run it — the third test should already pass, the others too**

Run: `.venv/bin/python -m pytest tests/test_run_ai_blobs.py -q`
Expected: PASS — `render_payload` already supports this. These tests pin behaviour the next step
must not break; they are a regression net, not a red-green cycle. **Do not skip them**: Task 8
deletes the renderers that currently guarantee separation, and these are what replace that
guarantee at this layer.

- [ ] **Step 3: Supply the blobs from `run`**

In `agent/run.py`, replace lines 69-77 (the research-only block and the `dashboard.html` write):

```python
    # AI tiers (all optional): if a pass wrote its document into this state, surface it in the AI
    # Frontier tab. Each rides as its OWN blob so the certified drift-data stays byte-identical —
    # the mechanical proof the AI tiers cannot touch the certified one.
    def _optional(name):
        path = os.path.join(state_dir, name)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None          # an unreadable AI blob hides its tier; it never fails the scan

    _write(os.path.join(state_dir, "dashboard.html"),
           render_payload(payload, now, bundle=build_bundle(doc, audit, now),
                          adhoc=_optional("adhoc.json"),
                          leads=_optional("leads.json"),
                          research=_optional("research.json")))
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/run.py tests/test_run_ai_blobs.py
git commit -m "feat(run): embed the adhoc and leads blobs in the dashboard"
```

---

### Task 8: The AI Frontier tab renders leads with provenance badges

**Files:**
- Modify: `agent/assets/dashboard.app.js` (blob loading near line 12; the `ai` tile group near line 131)
- Modify: `agent/assets/dashboard.template.html` (the AI Frontier plane, around lines 140-180 and the empty state at line 355)
- Modify: `agent/assets/dashboard.css` (badge styles)
- Test: `tests/test_dashboard_ai_tab.py` (create)

**Interfaces:**
- Consumes: the `leads-data` blob from Task 7.
- Produces: a `Leads` tile and a leads list in the AI Frontier plane. No Python interface.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard_ai_tab.py`:

```python
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent.parent / "agent" / "assets"


def test_app_js_consumes_the_leads_blob():
    """render_payload has emitted `leads-data` for some time, but nothing READ it — the blob went
    into the page and no surface showed it."""
    js = (_ASSETS / "dashboard.app.js").read_text()
    assert 'getElementById("leads-data")' in js
    assert "LEADS" in js


def test_ai_plane_has_a_leads_tile():
    js = (_ASSETS / "dashboard.app.js").read_text()
    assert 'label:"Leads"' in js
    assert "leadsCount" in js


def test_the_three_tiers_are_badged_distinctly():
    """One tab, but never one undifferentiated pile: gate-validated shapes, sourced research
    verdicts and unverified leads carry genuinely different trust and the UI must say so."""
    tpl = (_ASSETS / "dashboard.template.html").read_text()
    for badge in ("GATE-VALIDATED", "SOURCED", "UNVERIFIED LEAD"):
        assert badge in tpl, badge


def test_leads_are_never_labelled_certified():
    tpl = (_ASSETS / "dashboard.template.html").read_text()
    i = tpl.find("UNVERIFIED LEAD")
    assert i != -1
    assert "CERTIFIED" not in tpl[i:i + 400]
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard_ai_tab.py -q`
Expected: FAIL on all four.

- [ ] **Step 3: Load the blob in `dashboard.app.js`**

After the `RESEARCH` line (about line 15), add:

```javascript
  // the AI-LEADS tier (drift-leads/v1) — the rawest of the three: what an AI agent read in the
  // repo, corroborated only by that session. `retired` is a tri-state, NEVER a date. Separate
  // blob; null when no cross-check has run, so the tier is hidden rather than shown as 0.
  var LEADS = document.getElementById("leads-data") ? blob("leads-data") : null;
```

- [ ] **Step 4: Add the computed count and the tile**

In the `computed` block (alongside `researchedCount` / `shapedCount`), add:

```javascript
      leadsCount: function(){
        if(!LEADS) return 0;
        return (LEADS.repos || []).reduce(function(n, r){
          return n + ((r.integrations || []).length);
        }, 0);
      },
      leadRows: function(){
        if(!LEADS) return [];
        var out = [];
        (LEADS.repos || []).forEach(function(r){
          (r.integrations || []).forEach(function(i){
            out.push({repo: r.repo, vendor: i.vendor, host: i.host, endpoint: i.endpoint,
                      file: i.file, line: i.line, retired: i.retired, note: i.note,
                      origin: "lead"});
          });
        });
        return out;
      },
```

Add the tile to the `ai` plane's `tiles` array (after the `shaped` entry):

```javascript
            {key:"leads",label:"Leads",n:this.leadsCount},
```

- [ ] **Step 5: Render the rows with badges in `dashboard.template.html`**

Inside the AI Frontier plane, after the existing shaped/research sections, add:

```html
<!-- The three AI tiers share ONE tab but never one pile: each row states its provenance, because
     a gate-validated shape, a sourced research verdict and an unverified lead carry different
     trust. Collapsing that distinction is how a model's guess becomes indistinguishable from a
     fetched fact. -->
<section v-if="leadRows.length" class="ai-tier">
  <h3>Cross-check leads <span class="orig" data-origin="lead">UNVERIFIED LEAD</span></h3>
  <p class="muted">Read by an AI agent this session. Corroborated by nothing else — a lead says
     <em>whether</em>, never <em>when</em>. Promote one through <code>/drift-absorb</code> to make
     it a certified finding.</p>
  <table>
    <thead><tr><th>Vendor</th><th>Host</th><th>Where</th><th>Retired?</th><th>Evidence</th></tr></thead>
    <tbody>
      <tr v-for="r in leadRows" :key="r.repo + r.host + r.file + r.line">
        <td>{{ r.vendor }}</td>
        <td>{{ r.host }}</td>
        <td><code>{{ r.file }}<span v-if="r.line">:{{ r.line }}</span></code></td>
        <td><span class="tri" :data-tri="r.retired">{{ r.retired }}</span></td>
        <td class="muted">{{ r.note }}</td>
      </tr>
    </tbody>
  </table>
</section>
```

In the same plane, label the two existing tiers so all three badges are present. Add
`<span class="orig" data-origin="shaped">GATE-VALIDATED</span>` to the shaped section's heading and
`<span class="orig" data-origin="sourced">SOURCED</span>` to the research section's heading.

Update the empty state at line 355 so it counts three ways in, not two:

```html
        <p><b>No AI pass has run on this scan.</b> The AI Frontier fills in three ways: an AI
```

- [ ] **Step 6: Style the badges in `dashboard.css`**

```css
/* Provenance badges. Deliberately DESCENDING in visual weight — gate-validated reads strongest,
   an unverified lead weakest — so the eye ranks the tiers the way the trust model does. */
.orig[data-origin="sourced"] { background: var(--amber-bg, #fdf1dc); color: var(--amber-fg, #7a4b00); }
.orig[data-origin="lead"]    { background: var(--muted-bg, #eceff3); color: var(--muted-fg, #52606d);
                               border: 1px dashed currentColor; }
.tri[data-tri="yes"]     { font-weight: 700; }
.tri[data-tri="unknown"] { opacity: .7; font-style: italic; }
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard_ai_tab.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add agent/assets/dashboard.app.js agent/assets/dashboard.template.html \
        agent/assets/dashboard.css tests/test_dashboard_ai_tab.py
git commit -m "feat(dashboard): render AI leads in the AI Frontier tab, badged by provenance"
```

---

### Task 9: Delete the two side-car dashboards

**Files:**
- Delete: `agent/lib/probabilistic_render.py`, `agent/lib/adhoc_render.py`
- Delete: `tests/test_probabilistic_render.py`
- Modify: `agent/cli.py` (`_cmd_adhoc_report` at line 1209 — stop writing `adhoc.html`)
- Modify: `tests/test_probabilistic.py` (keep the `compare` tests, drop any render assertions)
- Test: `tests/test_no_side_car_dashboards.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 6-8.
- Produces: `adhoc-report` writes `adhoc.json` only. `agent.lib.probabilistic.compare` survives untouched.

- [ ] **Step 1: Write the failing test**

Create `tests/test_no_side_car_dashboards.py`:

```python
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_the_side_car_renderers_are_gone():
    """Three AI surfaces became one. These two files ARE the second and third dashboards; leaving
    either importable invites a caller to resurrect it."""
    assert not (_ROOT / "agent" / "lib" / "probabilistic_render.py").exists()
    assert not (_ROOT / "agent" / "lib" / "adhoc_render.py").exists()


def test_nothing_still_imports_them():
    hits = []
    for p in list((_ROOT / "agent").rglob("*.py")) + list((_ROOT / "tests").rglob("*.py")):
        if "probabilistic_render" in p.read_text() or "adhoc_render" in p.read_text():
            hits.append(str(p.relative_to(_ROOT)))
    assert not hits, f"still referencing a deleted renderer: {hits}"


def test_the_compare_logic_survives():
    """Only the RENDERING is deleted. compare() produced the agree/AI-only/tool-only tally and is
    now what feeds leads.json."""
    from agent.lib.probabilistic import compare
    assert callable(compare)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_no_side_car_dashboards.py -q`
Expected: FAIL — both files still exist.

- [ ] **Step 3: Stop `adhoc-report` writing HTML**

In `agent/cli.py`, in `_cmd_adhoc_report` (line 1209), remove the `from agent.lib.adhoc_render import ...`
import and the block that writes `adhoc.html`. Keep the `adhoc.json` write and the exit-3 behaviour
for an over-broad shape. Update its docstring's first line to:

```python
    """Write the ad-hoc (gate-validated) shape record to <state>/adhoc.json — the AI Frontier tab's
    SHAPED tier. It no longer writes a side-car HTML page: there is one dashboard.
```

Update the parser comment at line 1311 to `# POC: the ad-hoc / gate-validated middle tier -> adhoc.json`.

- [ ] **Step 4: Delete the files**

```bash
git rm agent/lib/probabilistic_render.py agent/lib/adhoc_render.py tests/test_probabilistic_render.py
```

Then open `tests/test_probabilistic.py` and delete any test that imports a renderer or asserts on
HTML; keep every test of `compare`.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. If a test fails on a missing import, it is a leftover reference — fix it rather
than restoring the file.

- [ ] **Step 6: Commit**

```bash
git add -A agent/cli.py agent/lib tests
git commit -m "refactor: delete the probabilistic and adhoc side-car dashboards"
```

---

### Task 10: `verify` gains the firewall invariant

**Files:**
- Modify: `agent/lib/verify.py` (add `check_ai_firewall`, register it in `verify_payload` at line 487)
- Test: `tests/test_verify_ai_firewall.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks at runtime; conceptually replaces the file-separation guarantee that Task 9 removed.
- Produces: `verify.check_ai_firewall(payload: dict) -> None`, raising `Violation("ai-firewall", detail)`. Registered in `verify_payload`, so `drift-scan verify` reports it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify_ai_firewall.py`:

```python
import pytest
from agent.lib import verify


def _clean():
    return {"counts": {"fixes": 0, "sunsets": 0}, "endpoints": [], "findings": [], "catalog": []}


def test_a_clean_payload_passes():
    verify.check_ai_firewall(_clean())


@pytest.mark.parametrize("payload", [
    {"counts": {}, "endpoints": [{"domain": "a.com", "origin": "ai"}], "findings": [], "catalog": []},
    {"counts": {}, "endpoints": [], "findings": [{"vendor": "X", "origin": "lead"}], "catalog": []},
    {"counts": {}, "endpoints": [], "findings": [], "catalog": [{"vendor": "X", "by": "lead"}]},
    {"counts": {}, "endpoints": [{"domain": "a.com", "tier": "ai-shaped"}], "findings": [],
     "catalog": []},
])
def test_an_ai_record_in_the_certified_payload_is_a_violation(payload):
    """Until now the firewall between certified findings and AI output WAS file separation: the AI
    lived in a different HTML file and verify only covered the certified ones. Once they share a
    document that structural guarantee is gone, so it has to become an executable check —
    otherwise 'merge the AI tab into the dashboard' silently weakens the tool's central claim."""
    with pytest.raises(verify.Violation) as exc:
        verify.check_ai_firewall(payload)
    assert exc.value.check == "ai-firewall"


def test_the_firewall_runs_as_part_of_verify_payload():
    dirty = {"counts": {}, "endpoints": [{"domain": "a.com", "origin": "ai"}],
             "findings": [], "catalog": []}
    names = [v.check for v in verify.verify_payload(dirty, [])]
    assert "ai-firewall" in names


def test_ai_provenance_on_an_ATTESTATION_is_still_allowed():
    """`by: ai-research` on a catalog attestation is a LEGITIMATE, gate-validated provenance marker
    (it already ships on ~40 vendors). The firewall targets AI-shaped FINDINGS and ENDPOINTS, not
    the honest labelling of who checked a vendor's page."""
    ok = _clean()
    ok["catalog"] = [{"vendor": "Mailgun", "verdict": "CURRENT", "by": "ai-research"}]
    verify.check_ai_firewall(ok)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_verify_ai_firewall.py -q`
Expected: FAIL with `AttributeError: module 'agent.lib.verify' has no attribute 'check_ai_firewall'`.

- [ ] **Step 3: Implement the invariant**

Add to `agent/lib/verify.py`, before `verify_payload`:

```python
# Markers that mean "a model produced this". `by: ai-research` is deliberately NOT here: on a
# catalog attestation it is an honest provenance label for a gate-validated check, and ~40 vendors
# legitimately carry it. What must never appear is an AI-shaped ENDPOINT or FINDING.
_AI_MARKERS = frozenset({"ai", "ai-shaped", "lead", "leads", "probabilistic", "unverified"})
_AI_FIELDS = ("origin", "tier", "source_tier", "provenance")


def check_ai_firewall(payload: dict) -> None:
    """No AI-derived record may appear in the certified payload.

    Until the AI tiers moved into dashboard.html, this was guaranteed structurally: leads lived in
    probabilistic.html, shapes in adhoc.html, and `verify` covered only the certified files. Sharing
    one document removes that guarantee, so it becomes an assertion instead. The AI blobs
    themselves stay OUTSIDE the equality check — they are not projections of drift.json and cannot
    be verified against it — but nothing they contain may cross into the certified data.
    """
    for section in ("endpoints", "findings", "catalog"):
        for rec in payload.get(section) or ():
            if not isinstance(rec, dict):
                continue
            for field in _AI_FIELDS:
                val = str(rec.get(field) or "").strip().lower()
                if val in _AI_MARKERS:
                    raise Violation(
                        "ai-firewall",
                        f"{section}[] record carries {field}={val!r} — AI-derived data must stay "
                        f"in its own blob (adhoc-data / leads-data / research-data), never in the "
                        f"certified payload")
            if section == "catalog" and str(rec.get("by") or "").lower() in ("lead", "ai"):
                raise Violation(
                    "ai-firewall",
                    f"catalog[] record for {rec.get('vendor')!r} claims by={rec.get('by')!r} — a "
                    f"catalog verdict may only come from a gate-validated attestation")
```

Register it in `verify_payload`'s tuple:

```python
    for fn, args in ((check_tile_counts, (payload, findings)),
                     (check_owner_split, (payload,)),
                     (check_row_labels_distinct, (payload,)),
                     (check_host_classes, (payload,)),
                     (check_ai_firewall, (payload,)),
                     (check_number_formats, (payload,))):
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_verify_ai_firewall.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/verify.py tests/test_verify_ai_firewall.py
git commit -m "feat(verify): assert the AI firewall now that the tiers share one document"
```

---

### Task 11: Update the plugin promptfile, docs and the runner guard

**Files:**
- Modify: `commands/drift-detector.md` (the AI-plane section)
- Modify: `tests/test_runner.py` (`test_plugin_scaffolding_present_and_wired` asserts on the old strings)
- Modify: `docs/POC-ADHOC-SHAPES.md`, `docs/ROADMAP.md`
- Modify: `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (version bump, both together)

**Interfaces:**
- Consumes: the finished behaviour from Tasks 6-10.
- Produces: no code interface. This is the task that stops the shipped instructions describing a surface that no longer exists.

- [ ] **Step 1: Write the failing test**

Replace the two AI assertions inside `test_plugin_scaffolding_present_and_wired` in
`tests/test_runner.py`:

```python
    # the firewall, enforced in the promptfile: AI output is leads in its OWN BLOB inside the one
    # dashboard (there is no second dashboard any more), and a lead's `retired` is a tri-state —
    # never a date (a date is a certified-tier claim only).
    assert "AI Frontier" in main and "leads.json" in main
    assert "probabilistic.html" not in main, "the side-car dashboard is gone; the promptfile must not send users to it"
    assert '"yes"|"no"|"unknown"' in main and "NEVER a date" in main
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_runner.py -q -k plugin_scaffolding`
Expected: FAIL — the promptfile still says `probabilistic.html`.

- [ ] **Step 3: Rewrite the promptfile's AI-plane step**

In `commands/drift-detector.md`, replace step 3 of "The AI plane" with:

```markdown
3. Record the leads — they ride in the ONE dashboard, not a second page:
   `"$SCAN" leads --state <state> --ai-results <state>/ai_results.json --now $(date +%F)`
   This validates the pass (refusing any date in a lead — `retired` is the tri-state
   `"yes"|"no"|"unknown"`, NEVER a date) and writes `<state>/leads.json`. Then re-run
   `"$SCAN" render --state <state>` so the dashboard picks it up. The leads appear in the
   **AI Frontier** tab badged `UNVERIFIED LEAD`, alongside gate-validated shapes
   (`GATE-VALIDATED`) and sourced research verdicts (`SOURCED`) — one surface, three
   clearly-separated tiers. The certified `drift.json` is untouched, and `verify`'s
   `ai-firewall` invariant proves it.
```

Update step 4 to point at the tab rather than the file: *"Show the tally (agree / AI-only /
tool-only) and point the user at the dashboard's AI Frontier tab."*

Search the file for any other `probabilistic.html` or `adhoc.html` mention and update it.

- [ ] **Step 4: Update the docs**

In `docs/POC-ADHOC-SHAPES.md`, replace references to `adhoc.html` with `adhoc.json` + the AI
Frontier tab. In `docs/ROADMAP.md`, mark the AI-surface consolidation done and note that
`probabilistic` is now `leads`.

- [ ] **Step 5: Bump both versions together**

`plugin.json` and `marketplace.json` **must** match — `test_runner.py` guards this because they
silently drifted for multiple releases and `claude plugin update` compares the marketplace version.
Set both to `0.19.0-beta`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add commands/drift-detector.md docs .claude-plugin tests/test_runner.py
git commit -m "docs(plugin): one AI surface — leads.json and the AI Frontier tab (0.19.0-beta)"
```

---

### Task 12: End-to-end proof on the reference repo

**Files:**
- No source changes. This task is the evidence that the two complaints are actually fixed.

**Interfaces:**
- Consumes: everything.
- Produces: a recorded before/after the reviewer can check.

- [ ] **Step 1: Scan the reference repo from a NEUTRAL cwd**

```bash
cd /tmp && /path/to/drift-detector-scan/bin/drift-scan run \
  --root /home/tops/Projects/sandbox/promoteplus-crm \
  --state /tmp/drift-e2e --now "$(date +%F)"
```

Run from `/tmp`, never from a directory containing an `agent/` package. (`PYTHONSAFEPATH=1` now
prevents the hijack, but the habit is what keeps the result trustworthy.)

- [ ] **Step 2: Confirm the queue collapsed**

```bash
cd /tmp && /path/to/drift-detector-scan/bin/drift-scan research --state /tmp/drift-e2e
```

Expected: **at most 2 hosts**, and `idximages.directaxess.com` should be among them — it is a
genuine third party and is deliberately still queued. Before this plan it printed 27.
If a host you expected to be bucketed is still listed, fix its catalog entry rather than the test.

- [ ] **Step 3: Confirm verify is green, including the new invariant**

```bash
cd /tmp && /path/to/drift-detector-scan/bin/drift-scan verify --state /tmp/drift-e2e
```

Expected: exit 0, "report is self-consistent". Then prove the firewall actually bites:
temporarily add `"origin": "ai"` to one endpoint in `/tmp/drift-e2e/drift.json`, re-run `verify`,
and confirm it fails with `[ai-firewall]`. Restore the file.

- [ ] **Step 4: Confirm there is exactly one dashboard**

```bash
ls /tmp/drift-e2e
```

Expected: `dashboard.html` present; **no** `probabilistic.html`, **no** `adhoc.html`.
Then run a leads pass and confirm the blob lands in the one page:

```bash
cd /tmp && /path/to/drift-detector-scan/bin/drift-scan leads --state /tmp/drift-e2e \
  --ai-results <an ai_results.json> --now "$(date +%F)"
cd /tmp && /path/to/drift-detector-scan/bin/drift-scan render --state /tmp/drift-e2e
grep -c 'id="leads-data"' /tmp/drift-e2e/dashboard.html    # expect 1
```

- [ ] **Step 5: Record the numbers and commit the evidence**

Append the before/after (queued 27 → N, tracked 11 → N, unaudited 2 → N) to
`docs/superpowers/plans/2026-08-12-ai-surface-and-queue.md` under a new "## Result" heading.

```bash
git add docs/superpowers/plans/2026-08-12-ai-surface-and-queue.md
git commit -m "docs(plan): record the end-to-end result on the reference repo"
```

---

## Self-review

**Spec coverage:** Part 1 → Tasks 1-5 (reputation catalog, reserved TLDs, own-infra derivation and
its wiring, ten vendors). Part 2 → Tasks 6-9 (leads producer, blob wiring, front-end tab, deleting
the side-cars). Part 3 → Task 10 (firewall invariant). The spec's testing section is distributed
across every task's red-green steps; its risk section is addressed by Task 3's public-forge and
short-token tests and Task 4's ordering test. Docs and the promptfile — implied by the spec's
deletions and easy to forget — are Task 11. Task 12 covers the spec's stated expected result
(27 → ~1) as an executable check.

**Placeholder scan:** none. Every code step carries the code; every command carries its expected
output. Two steps deliberately say "check the actual signature first" (Task 5's loader name, Task 6's
`compare` return shape) with an explicit fallback — that is verification, not a placeholder.

**Type consistency:** `own_infra.signals(repo_path, repo_id) -> {"tokens": set, "domains": set}` is
defined in Task 3 and consumed in Task 4 with those exact names. `host_class.classify(..., own=)`
matches between Tasks 4's test and its implementation. `leads.json`'s `drift-leads/v1` shape is
defined in Task 6 and consumed by Task 7 (`_optional("leads.json")`) and Task 8 (`LEADS.repos[].integrations[]`).
`verify.check_ai_firewall(payload)` and `Violation.check == "ai-firewall"` agree across Task 10.

---

## Result

End-to-end run on the reference repo (`promoteplus-crm`), 2026-08-12, executed per Task 12 from a
neutral `/tmp` cwd with `PYTHONSAFEPATH=1` and the persistent local catalog
(`DRIFT_CATALOG_DIR=$HOME/.drift/catalog`). State dir: `/tmp/drift-e2e`.

**1. Queue collapse — `drift-scan research`**
Before this branch: 27 hosts. After: **1 host** — `idximages.directaxess.com`, exactly the one
vendor the plan named as deliberately still queued (genuine third party, no catalog match yet).
Meets expectation (≤ 2, with that host present).

**2. `drift-scan verify` + the `ai-firewall` invariant**
Clean run: exit 0, `report is self-consistent — 0 sunsets, 0 eol, 12 unaudited-vendor(s)`.
Injected `"origin": "ai"` into `endpoints[0]` of `drift.json`, re-ran verify: exit 3, failed with
`[ai-firewall] endpoints[] record carries origin='ai' — AI-derived data must stay in its own blob
...` (plus two expected knock-on `[blob-parity]` violations, since only `drift.json` was edited,
not the HTML projections). Restored the file from a backup, re-ran verify: exit 0, green again.
Meets expectation.

**3. Exactly one dashboard**
`/tmp/drift-e2e` contains `dashboard.html`; no `probabilistic.html`, no `adhoc.html` (also present:
`chart.html`, which is a separate, still-current artifact — not one of the retired side-cars).
Leads pass: `drift-scan leads --ai-results <fixture> --now <date>` → `0 agree · 1 AI-only ·
19 tool-only`, written to `leads.json`. `drift-scan render` → `dashboard.html rewritten (certified
+ leads)`. `grep -c 'id="leads-data"' dashboard.html` → **1**. Meets expectation.

**4. Catalog counts, from `drift.json.counts.coverage` / `counts.unaudited`**

| metric     | before (plan) | after (measured) |
|------------|---------------|-------------------|
| queued     | 27            | **1**             |
| tracked    | 11            | **27**            |
| unaudited  | 2             | **12**            |

`tracked` and `unaudited` both moved *up*, not down — this is the expected shape of the fix, not a
regression: the 27 previously-`queued` hosts were sitting unclassified because host classification
couldn't place them. With the reputation catalog, reserved-TLD handling, and own-infra derivation
from Tasks 1-5, almost all of them now resolve to a definite bucket — most become `tracked`
(real third-party APIs now recognized and catalogued, most still `unaudited` pending a live check)
or fall into `na`/excluded classes (own-infra, boilerplate, social-widget, vendored-lib, asset-cdn:
44 hosts). Only one host — the one named above — remains genuinely ambiguous and stays queued for
research. Full catalog for this run: 21 vendors, 12 UNAUDITED, 9 CURRENT (Mailgun, Mailchimp,
Google OAuth2, OpenAI, Anthropic, Microsoft Graph, OpenStreetMap, SendGrid, Twilio).

**Overall:** all five Task 12 measurements met their stated expectations. Nothing was adjusted to
make a number look better; the `tracked`/`unaudited` increase is reported as measured, with the
reasoning above for why it is the correct direction given what those buckets mean.

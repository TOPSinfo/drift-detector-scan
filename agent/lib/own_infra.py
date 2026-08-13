"""Derive the hosts that are the SCANNED REPO'S OWN infrastructure, from the repo itself.

Client hostnames cannot be catalogued: agent/host_reputation.yaml ships in a public repo, so a
client's staging box must never be written into it. They also cannot be pattern-guessed — a
`cdn.*` / `qa-*` heuristic would claim a genuine third-party CDN, which is the false confidence
this tool exists to refuse. So they are DERIVED, per scan, from what the repo already tells us.

Three signals:

  token      the repo's name contributes a distinctive token (`promoteplus-crm` -> `promoteplus`),
             and a host containing it is that project's own box.
  domain     a SELF-HOSTED forge remote (git.acme.internal/...) names the organisation's own
             domain. Public forges are excluded — a github.com remote says nothing about who owns
             api.github.com.
  confirmed  a reviewed entry from the own-domains overlay (agent/lib/own_domains.py) — an AI
             resolution pass's claim that survived a gate, not derived from the repo at all. It
             matches STRONG, like `domain` (exact host or subdomain suffix), never like a token
             substring: see docs/superpowers/specs/2026-08-13-no-queue-design.md.

Config-derived inference (APP_URL, composer/package name) was measured on a real repo and
rejected: APP_URL was `http://localhost` and the composer name was the framework default
`laravel/laravel`. A signal that real projects leave at default is not a signal.

The two signals carry different weight, and callers that drop a host out of the audit backlog
entirely must respect that: `token` is a heuristic guess from the repo's own name (plausible, not
certain), `domain` is the git-remote org's actual identity (strong). See `reason`/`is_token_claim`
below — a token claim alone is not grounds to remove a host from view, only to label it.

`_registrable`'s public-suffix rule (`_SLD_GENERICS` + a bare 2-letter ccTLD) covers the general
`{generic}.{cctld}` family, but it is NOT a Public Suffix List: an uncovered ccTLD second-level
that isn't an ordinary English generic (`nic.in`) or a 3-label suffix (`nsw.gov.au`) will still
resolve to the wrong registrable domain. A true fix needs the real PSL, not a hand-rolled rule.

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
    # Descriptive nouns for what a repo DOES, not who it belongs to — a repo named
    # `shipping-tracker-app` describes an integration SHAPE, not an organisation, and its
    # generic half ("tracker") must not claim the very vendor host ("tracker.aftership.com")
    # it exists to call. Measured: shipping-tracker-app -> tracker.aftership.com falsely
    # own-infra before these were added.
    "connector", "connectors", "bridge", "bridges", "tracker", "trackers", "shipping",
    "payments", "payment", "gateway", "gateways", "invoice", "invoices", "manager", "managers",
    "wrapper", "wrappers", "adapter", "adapters", "handler", "handlers", "processor",
    "processors", "importer", "exporter", "scheduler", "middleware", "billing", "checkout",
    "fulfillment", "logistics", "notification", "notifications", "messaging", "consumer",
    "producer", "pipeline", "integration", "integrations",
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

# Public suffixes that are themselves two labels wide (`co.uk`, not `com`). Naively taking the
# last two labels of a host under one of these turns the SUFFIX into the "registrable domain" —
# `git.example.co.uk` -> `co.uk` — which then claims every unrelated `*.co.uk` vendor as
# own-infra. The real organisation label sits one level further up, so hosts ending in one of
# these need three labels, not two.
#
# This used to be a ~20-entry hardcoded list of specific `{second-level}.{cctld}` pairs
# (`co.uk`, `com.au`, `co.jp`, ...). That is a false-confidence surface: the world has hundreds
# of ccTLDs, most with their own `co.`/`com.`/`gov.`/`ac.` second level, and every pair not
# enumerated (`com.cn`, `co.kr`, `com.mx`, `co.il`, `com.sg`, `com.hk`, `gov.uk`, ...) silently
# fell through to being treated as an organisation domain — exactly the wrong direction, since a
# missed entry then claims an unrelated vendor as own-infra instead of leaving it queued. So the
# check below is a RULE, not a list: a two-label result is a public suffix whenever its first
# label is one of the well-known second-level generics and its second label is a bare 2-letter
# ccTLD. That single rule covers the whole `{generic}.{cctld}` family without enumerating it.
#
# What the rule genuinely cannot express stays here: ccTLD second levels that aren't ordinary
# English generics (`me.uk`, `ltd.uk`, `plc.uk`), and vendor-operated suffixes where every
# customer gets a subdomain — the suffix itself is never anyone's organisation (`github.io`,
# `gitlab.io`, `pages.dev`, `herokuapp.com`, `vercel.app`).
_MULTI_PART_SUFFIXES = frozenset({
    "me.uk", "ltd.uk", "plc.uk",
    "github.io", "gitlab.io", "pages.dev", "herokuapp.com", "vercel.app",
})

# Well-known second-level generic labels reused across many ccTLDs' public-suffix hierarchies
# (`co`, `com`, `gov`, `ac`, ... under `.uk`, `.cn`, `.kr`, `.au`, ...). Paired with a bare
# 2-letter ccTLD, this is the general public-suffix rule above.
_SLD_GENERICS = frozenset({
    "co", "com", "org", "net", "gov", "ac", "edu", "mil", "int", "ne", "or",
    "gob", "gouv", "gv", "id", "sch", "nom", "art", "priv",
})

_CCTLD = re.compile(r"^[a-z]{2}$")


def _is_public_suffix(two_labels: str) -> bool:
    if two_labels in _MULTI_PART_SUFFIXES:
        return True
    first, _, second = two_labels.partition(".")
    return first in _SLD_GENERICS and bool(_CCTLD.match(second))

_REMOTE = re.compile(r"^(?:(?:https?|ssh|git)://)?(?:[^@/]+@)?([^/:]+)[/:](.+?)(?:\.git)?/?$")


def _tokens(name: str) -> set:
    return {t for t in re.split(r"[-_.]+", (name or "").lower())
            if len(t) >= _MIN_TOKEN and t.isalnum() and t not in _GENERIC}


def _registrable(host: str) -> str:
    labels = [l for l in (host or "").lower().split(".") if l]
    if len(labels) < 2:
        return ""
    two = ".".join(labels[-2:])
    if _is_public_suffix(two):
        # Need an organisation label above the suffix itself; with none, the host IS the
        # suffix (or the suffix with nothing but itself) — a public suffix is not an
        # organisation, so claim nothing rather than risk a false own-infra match.
        if len(labels) < 3:
            return ""
        return ".".join(labels[-3:])
    return two


def signals(repo_path: str = "", repo_id: str = "", vendor_tokens: frozenset = frozenset(),
           confirmed: frozenset = frozenset()) -> dict:
    """{'tokens', 'domains', 'confirmed'} — everything derivable about this repo's own identity.

    `repo_path` is the checkout directory; `repo_id` is the git remote (or the identity string
    `scope_edges.identity` normalises), either of which may be absent. `vendor_tokens` is the
    set of vendor-name tokens the caller (which owns the catalog — this module deliberately does
    not load one) already knows about; any derived token that collides with one is dropped, so a
    repo named after its own vendor (`acme-mailgun-sync`) cannot suppress that vendor's host.

    `confirmed` is the set of domains an own-domains overlay entry (agent/lib/own_domains.py)
    already scoped to THIS repo — the caller (endpoints.scan_endpoints) does that scoping, this
    function only classifies. The SAME vendor-collision guard applies: a confirmed domain that
    names a catalogued vendor is dropped here, non-negotiably — see module docstring and
    docs/superpowers/specs/2026-08-13-no-queue-design.md's "Risks" section. Callers must never
    route around this by constructing `domains` from unreviewed data instead.
    """
    tokens = _tokens(os.path.basename((repo_path or "").rstrip("/")))
    domains: set = set()
    m = _REMOTE.match((repo_id or "").strip())
    if m:
        host, path = m.group(1), m.group(2)
        tokens |= _tokens(path.rstrip("/").split("/")[-1])
        host_l = host.lower()
        reg = _registrable(host)
        if reg and reg not in _PUBLIC_FORGES and host_l not in _PUBLIC_FORGES:
            domains.add(reg)
    # A derived token is dropped when it EQUALS a vendor token (the original guard) or when it
    # CONTAINS a vendor token of length >= _MIN_TOKEN. The equality-only check missed a repo
    # token that concatenates onto or around a vendor's name (`globalpaymentsapi` contains
    # `globalpayments` but never equals it) — a repo token that contains a vendor's name is
    # still that vendor's name. Over-dropping is the SAFE direction here: a dropped token merely
    # leaves the host visible in the queue for a human to triage, whereas a kept one silently
    # deletes a real vendor from the audit backlog — this project's cardinal sin. The length
    # floor keeps a short vendor token (`api`, `sp`) from vetoing on a coincidental substring.
    tokens = {t for t in tokens
              if t not in vendor_tokens
              and not any(len(vt) >= _MIN_TOKEN and vt in t for vt in vendor_tokens)}
    # The non-negotiable guard, restated for the overlay: a REVIEWED confirmed domain gets no
    # more trust than a repo-derived token when it collides with a catalogued vendor's name —
    # the vendor always wins. Same equality-or-contains check as the token guard above, same
    # over-dropping-is-safe reasoning (a dropped confirmation leaves the host visible for a
    # human/AI to re-triage; a kept one silently deletes a real vendor from the audit backlog).
    confirmed_domains = {d.lower() for d in confirmed
                         if d and d.lower() not in vendor_tokens
                         and not any(len(vt) >= _MIN_TOKEN and vt in d.lower() for vt in vendor_tokens)}
    return {"tokens": tokens, "domains": domains, "confirmed": confirmed_domains}


def _claim(host: str, sig: dict):
    """The strongest signal claiming `host`: `("domain", value)`, `("confirmed", value)`, or
    `("token", value)`, or None if none fire. `domain` and `confirmed` are checked first — both
    are strong claims (a self-hosted forge's own identity; a reviewed overlay confirmation) —
    `token` is the repo-name heuristic, weaker (see the module docstring). `is_own` doesn't care
    which one matched; `reason` does, so callers that must treat them differently (F1: a token
    claim is not strong enough to drop a host out of the research backlog, only a strong claim
    is) can tell them apart."""
    h = (host or "").lower()
    if not h:
        return None
    for d in sig.get("domains") or ():
        if h == d or h.endswith("." + d):
            return ("domain", d)
    for d in sig.get("confirmed") or ():
        if h == d or h.endswith("." + d):
            return ("confirmed", d)
    for t in sig.get("tokens") or ():
        if t in h:
            return ("token", t)
    return None


def is_own(host: str, sig: dict) -> bool:
    """Is `host` this repo's own infrastructure? False on no signal — failing toward SHOWN."""
    return _claim(host, sig) is not None


_REASON_LABEL = {"domain": "git remote org domain", "token": "repo token",
                 "confirmed": "confirmed own domain"}


def reason(host: str, sig: dict) -> str | None:
    """A human-readable description of WHY `host` was claimed as own-infra, naming the exact
    signal and the value that matched it — e.g. "repo token 'promoteplus'" or "git remote org
    domain 'topsdemo.in'". None when no signal claims the host. This is what lets a caller (and a
    report reader) see the claim instead of a silent disappearance — recorded on the endpoint
    record as `ownInfraReason` (see agent/lib/endpoints.py)."""
    claim = _claim(host, sig)
    if claim is None:
        return None
    kind, val = claim
    return f"{_REASON_LABEL[kind]} '{val}'"


def is_token_claim(reason_text: str | None) -> bool:
    """True when a `reason()` string names the WEAK repo-name-token signal rather than the
    strong git-remote org-domain one. A token is a heuristic guessed from the scanned repo's own
    name — plausible, not certain — so a caller (dashboard_render's coverage lifecycle) that
    would otherwise drop an own-infra host out of the research backlog must check this first and
    keep a token-claimed host queued instead; a domain-claimed host is dropped as before."""
    return bool(reason_text) and reason_text.startswith(_REASON_LABEL["token"] + " ")

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

# Public suffixes that are themselves two labels wide (`co.uk`, not `com`). Naively taking the
# last two labels of a host under one of these turns the SUFFIX into the "registrable domain" —
# `git.example.co.uk` -> `co.uk` — which then claims every unrelated `*.co.uk` vendor as
# own-infra. The real organisation label sits one level further up, so hosts ending in one of
# these need three labels, not two.
_MULTI_PART_SUFFIXES = frozenset({
    "co.uk", "org.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk", "sch.uk",
    "com.au", "net.au", "org.au", "edu.au",
    "co.nz", "org.nz", "net.nz",
    "co.za", "com.br", "co.jp", "co.in", "co.id",
    "github.io", "gitlab.io",
})

_REMOTE = re.compile(r"^(?:(?:https?|ssh|git)://)?(?:[^@/]+@)?([^/:]+)[/:](.+?)(?:\.git)?/?$")


def _tokens(name: str) -> set:
    return {t for t in re.split(r"[-_.]+", (name or "").lower())
            if len(t) >= _MIN_TOKEN and t.isalnum() and t not in _GENERIC}


def _registrable(host: str) -> str:
    labels = [l for l in (host or "").lower().split(".") if l]
    if len(labels) < 2:
        return ""
    two = ".".join(labels[-2:])
    if two in _MULTI_PART_SUFFIXES:
        # Need an organisation label above the suffix itself; with none, the host IS the
        # suffix (or the suffix with nothing but itself) — a public suffix is not an
        # organisation, so claim nothing rather than risk a false own-infra match.
        if len(labels) < 3:
            return ""
        return ".".join(labels[-3:])
    return two


def signals(repo_path: str = "", repo_id: str = "", vendor_tokens: frozenset = frozenset()) -> dict:
    """{'tokens', 'domains'} — everything derivable about this repo's own identity.

    `repo_path` is the checkout directory; `repo_id` is the git remote (or the identity string
    `scope_edges.identity` normalises), either of which may be absent. `vendor_tokens` is the
    set of vendor-name tokens the caller (which owns the catalog — this module deliberately does
    not load one) already knows about; any derived token that collides with one is dropped, so a
    repo named after its own vendor (`acme-mailgun-sync`) cannot suppress that vendor's host.
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
    tokens -= vendor_tokens
    return {"tokens": tokens, "domains": domains}


def is_own(host: str, sig: dict) -> bool:
    """Is `host` this repo's own infrastructure? False on no signal — failing toward SHOWN."""
    h = (host or "").lower()
    if not h:
        return False
    if any(h == d or h.endswith("." + d) for d in sig.get("domains") or ()):
        return True
    return any(t in h for t in sig.get("tokens") or ())

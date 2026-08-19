"""The needs-human ledger: hosts a resolution pass looked at and could not settle.

The resolve gate has always accepted `unknown` — "I could not tell" — as a first-class
verdict, deliberately, so nobody is pressured into inventing an own-domain or a vendor to
empty a work-list. But the verdict was returned in a summary dict and persisted nowhere, so
the next deterministic scan re-derived those hosts as `queued`. That collapsed two very
different states into one: *the pass ran and could not tell* vs *nobody has looked yet*.
Principle 1 is exactly this distinction, so the ledger is what makes `needs-human` reachable.

This is the mirror of `own_domains.py`, and for the same reason it is overlay-only: these are
CLIENT hostnames and can never enter the public tree. A missing overlay dir/file means no
verdicts have been recorded — absent, not empty-and-therefore-clean.

Entry shape (every field required — an entry with no note is a verdict with no reasoning,
which is what this ledger exists to refuse):

    - host: www.example-shipper.com
      repo: example-org/inventory-app
      by: ai-resolution
      checked: '2026-08-15'
      note: "fetched the page; it renders only the word 'Welcome' — nothing identifies an owner"

Scoped by repo+host: two clients can share one overlay directory, and an unknown recorded
against one repo must not silently settle the same host in another.

Pure: this module never opens a file itself; catalog_overlay is the one loader that does.
"""
from __future__ import annotations

from agent.lib import catalog_overlay

_REQUIRED = ("host", "repo", "by", "checked", "note")


def load() -> list:
    """Every recorded entry, or [] when no overlay is configured."""
    return [e for e in catalog_overlay.load_list(catalog_overlay.NEEDS_HUMAN)
            if isinstance(e, dict) and all(e.get(k) for k in _REQUIRED)]


def recorded_keys(entries: list | None = None) -> set:
    """{(repo, host-lowercased)} — the lookup the scan derives coverage from."""
    return {(e.get("repo"), str(e.get("host") or "").lower())
            for e in (load() if entries is None else entries)}

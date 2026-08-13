"""The confirmed-own-domains overlay: reviewed evidence an AI resolution pass (a later task)
lands, that lets the deterministic scanner re-derive `own-infra` for a host it previously had
to leave `queued`.

This is the *data path* half of the no-queue design
(docs/superpowers/specs/2026-08-13-no-queue-design.md): the AI never writes the verdict — it
writes evidence here, a gate (a later task) validates it, and `agent/lib/own_infra.py` treats a
confirmed entry as a STRONG signal (matches like the git-remote org domain: exact host or
subdomain suffix), never a token guess. The non-negotiable guard — a domain that names a
catalogued vendor can never become own-infra — lives in own_infra.signals(), not here; this
module only shapes what the overlay file holds.

Client hostnames can never enter the public tree, so unlike the other catalogs (vendors,
idioms, sunsets, attestations, sdk_profiles) there is no package baseline to layer — this is
overlay-only, read from $DRIFT_CATALOG_DIR/own_domains.local.yaml via catalog_overlay.load_list,
the one thing that touches disk. A missing overlay dir/file means no confirmations exist yet:
absent, not empty-and-therefore-clean.

Entry shape (each field required — a wrong entry silently removes a real third party from the
audit backlog, so an unevidenced entry is an error, never a silent skip):

    - repo: acme-org/acmegrocer-foods
      domain: acmegrocer.com
      by: ai-resolution
      checked: '2026-08-13'
      reason: "the project's own product domain; APP_URL and the repo name both name it"

Pure: this module never opens a file itself; catalog_overlay is the one loader that does.
"""
from __future__ import annotations

from agent.lib import catalog_overlay

_REQUIRED = ("repo", "domain", "by", "checked", "reason")


class OwnDomainError(ValueError):
    """A malformed own-domains overlay entry. Loud, never silently dropped — a dropped
    confirmation is invisible, but a KEPT malformed one (no reason, no reviewer) is worse."""


def load() -> dict:
    """{repo: frozenset(domain, ...)} from the own-domains overlay. {} when the overlay dir is
    unset or the file is absent (own_infra's `confirmed` guard already fails toward SHOWN, so an
    empty table changes nothing — no confirmations means every host stays exactly as it was)."""
    raw = catalog_overlay.load_list(catalog_overlay.OWN_DOMAINS)
    table: dict = {}
    for i, entry in enumerate(raw):
        where = f"own_domains entry #{i} ({entry.get('repo') if isinstance(entry, dict) else entry!r})"
        if not isinstance(entry, dict):
            raise OwnDomainError(f"{where}: not a mapping")
        for req in _REQUIRED:
            if not entry.get(req):
                raise OwnDomainError(f"{where}: missing required `{req}`")
        table.setdefault(entry["repo"], set()).add(str(entry["domain"]).lower())
    return {repo: frozenset(domains) for repo, domains in table.items()}

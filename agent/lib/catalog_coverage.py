"""Per-vendor catalog coverage: is this vendor's retirement list actually checked?

The shape verdict (agent/lib/shapes.py) answers "can we SEE this repo's calls?". This
answers the other half — "have we been TAUGHT what this vendor retires?" — because the
tool was honest about the first and silent about the second, and a vendor with 272
detected call-sites and no catalog entries rendered exactly like a clean one.

The unit is an ATTESTATION, not an entry count, and the difference is the whole design:

    entry count   a claim about our own file. Gameable — one junk entry flips a vendor
                  from "unaudited" to "audited" — and unknowable, because completeness
                  cannot be judged from the inside. eBay had twelve entries while the
                  vendor's page still listed operations we lacked.
    attestation   a claim about the world: somebody opened this vendor's canonical
                  deprecation page on a stated date and reconciled it.

So a vendor with entries but no attestation is UNAUDITED. That is deliberate, and it
grades our own eBay coverage honestly rather than flatteringly.

Deterministic: `now` is a pipeline input, so the same inputs give the same verdicts.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from agent.lib import catalog_overlay

_DEFAULT = str(Path(__file__).resolve().parent.parent / "catalog_attestations.yaml")

# Vendors publish on their own cadence; a quarter is the coarsest window in which a
# missed retirement is still likely to be actionable rather than already past.
STALE_DAYS = 90

CURRENT = "CURRENT"
STALE = "STALE"
UNAUDITED = "UNAUDITED"
# Checked, and REFUSED. The vendor publishes retirements only behind a partner/seller login
# nobody here holds. Distinct from UNAUDITED on purpose: one is unworked, the other is
# externally blocked, and a reader who cannot tell them apart will chase the wrong one.
# It is NOT an attestation — it never becomes CURRENT and its call-sites keep counting as
# unchecked exposure (principle 1: naming why we are blind does not make us sighted).
BLOCKED = "BLOCKED"

NO_ATTESTATION = "no-catalog-attestation"
ACCESS_BLOCKED = "partner-access-required"
CATALOG_STALE = "catalog-stale"
# The whole vendor API is catalogued as retired, so there is nothing left to audit:
# no future retirement can be missed once every version is already gone.
WHOLE_API_RETIRED = "whole-api-retired"


def load_attestations(path: str | None = None) -> dict:
    """{vendor: {checked, source, note, by, blocked}}. Absent file is fine — all UNAUDITED."""
    p = path or _DEFAULT
    try:
        with open(p, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or []
    except FileNotFoundError:
        return {}
    # a default load layers the overlay (baseline first); a later entry for a vendor wins,
    # so a re-attestation in the overlay updates the date the scan trusts.
    if path is None:
        raw = list(raw) + catalog_overlay.load_list(catalog_overlay.ATTESTATIONS)
    out = {}
    for a in raw:
        if not isinstance(a, dict) or not a.get("vendor"):
            continue
        blk = a.get("blocked")
        if blk is not None:
            # BLOCKED nests its OWN provenance, and the entry carries no top-level
            # checked/source. That is not tidiness — it is what makes the data safe to deploy
            # ahead of the code. The catalog overlay ships independently of the scanner, so a
            # BLOCKED entry WILL be read by scanners older than this verdict; encoded flat,
            # they ignored the key they did not know, saw a complete attestation, and rendered
            # the vendor CURRENT — "checked, fine" — from evidence saying its docs cannot be
            # read at all. Nested, an older loader finds no checked/source, skips the entry,
            # and falls back to UNAUDITED: it under-claims instead of over-claiming.
            # The flat form is REFUSED (not merely ignored) so the unsafe encoding, which
            # would mean two scanner versions reading opposite verdicts off the same bytes,
            # cannot be committed back in quietly.
            if not isinstance(blk, dict) or a.get("checked") or a.get("source"):
                continue
            since, src = blk.get("since"), blk.get("source")
            if not (since and src):
                continue                    # a block with no provenance is just an assertion
            out[a["vendor"]] = {"checked": str(since), "source": str(src),
                                "note": a.get("note", ""), "by": str(a.get("by") or "human"),
                                "blocked": str(blk.get("why") or "")}
            continue
        if a.get("checked") and a.get("source"):
            # `by` records provenance: "human" (default) vs "ai-research". An AI-attested "current"
            # is weaker than a human one — a missed sunset renders green and nobody re-checks green —
            # so it is surfaced distinctly and still governed by the same STALE_DAYS TTL.
            # `blocked` must be copied here, not just read in verdict_for: this whitelist is
            # the only path from YAML to verdict, and dropping the key turned three vendors
            # whose docs are provably unreachable into CURRENT — the strongest claim in the
            # vocabulary, produced from evidence that said the opposite.
            out[a["vendor"]] = {"checked": str(a["checked"]), "source": str(a["source"]),
                                "note": a.get("note", ""), "by": str(a.get("by") or "human"),
                                "blocked": ""}
    return out


def _age_days(checked: str, now: str) -> int | None:
    try:
        return (date.fromisoformat(now) - date.fromisoformat(checked)).days
    except ValueError:
        return None


def verdict_for(vendor: str, attestations: dict, now: str, *, stale_days: int = STALE_DAYS):
    """(verdict, reasons, checked_date) for one vendor."""
    att = attestations.get(vendor)
    if not att:
        return UNAUDITED, [NO_ATTESTATION], None
    # `blocked:` records a check that was REFUSED. `checked` is kept — the gate page was
    # really fetched on that date — but it never ages into CURRENT, so a re-check that is
    # still blocked simply restates the block rather than expiring into false confidence.
    if att.get("blocked"):
        return BLOCKED, [ACCESS_BLOCKED], att.get("checked")
    age = _age_days(att["checked"], now)
    if age is None or age > stale_days:
        return STALE, [CATALOG_STALE], att["checked"]
    return CURRENT, [], att["checked"]


def build(endpoints: list, sunsets: list, attestations: dict, now: str,
          *, stale_days: int = STALE_DAYS) -> list:
    """One record per vendor we actually DETECTED, sorted by exposure.

    Keyed on detected vendors, not on catalog vendors: the question is "what are we
    calling that nobody has checked?", so a catalogued vendor this codebase never calls
    is not a gap, and a heavily-called vendor with an empty catalog is the loudest one.
    """
    seen: dict = {}
    for e in endpoints:
        v = e.get("vendor")
        if not v or v == "Unknown" or not e.get("classified"):
            continue
        seen[v] = seen.get(v, 0) + (e.get("file_count") or 0)

    entries: dict = {}
    # Vendors whose ENTIRE API is catalogued as retired (`version: "*"`). These cannot be
    # "not yet checked": the catalog already says every version is gone, and the `*` entry
    # flags every call-site, so findings here are the opposite of zero. Leaving them
    # UNAUDITED put dead marketplaces on the human work-order asking someone to open a
    # seller portal that shut down with the company — a task that can never succeed.
    # Undated closures count too (`status: deprecated-no-date`): requiring a date would
    # keep exactly the messiest closures on the list forever.
    whole_api_dead: set = set()
    for s in sunsets:
        if s.get("vendor"):
            entries[s["vendor"]] = entries.get(s["vendor"], 0) + 1
            if s.get("version") == "*" and (s.get("retires") or s.get("status")):
                whole_api_dead.add(s["vendor"])

    out = []
    for vendor, sites in seen.items():
        verdict, reasons, checked = verdict_for(vendor, attestations, now,
                                                stale_days=stale_days)
        if verdict != CURRENT and vendor in whole_api_dead:
            # off the work-list, but say why — this is not an attestation and must not
            # read like one (`checked` and `source` stay empty).
            verdict, reasons = CURRENT, [WHOLE_API_RETIRED]
        att = attestations.get(vendor) or {}
        out.append({"vendor": vendor, "callSites": sites,
                    "catalogEntries": entries.get(vendor, 0),
                    "verdict": verdict, "reasons": reasons,
                    "checked": checked, "source": att.get("source", ""),
                    "by": att.get("by", "human")})   # provenance: human vs ai-research
        if verdict == BLOCKED:
            out[-1]["blocked"] = att.get("blocked", "")   # WHAT would unblock it, in words
    # loudest first: unaudited before stale before current, then by exposure
    rank = {UNAUDITED: 0, BLOCKED: 1, STALE: 2, CURRENT: 3}
    out.sort(key=lambda r: (rank[r["verdict"]], -r["callSites"], r["vendor"]))
    return out


def summary(records: list) -> dict:
    return {
        "unaudited": sum(1 for r in records if r["verdict"] == UNAUDITED),
        "blocked": sum(1 for r in records if r["verdict"] == BLOCKED),
        "stale": sum(1 for r in records if r["verdict"] == STALE),
        "current": sum(1 for r in records if r["verdict"] == CURRENT),
        # the number that matters: call-sites nobody has checked a retirement list for
        "unauditedCallSites": sum(r["callSites"] for r in records
                                  if r["verdict"] != CURRENT),
    }

"""Reconcile a vendor's PUBLISHED API specs against our curated sunset catalog.

Deliberately NOT a multi-vendor adapter framework yet. Measuring Amazon — the
best-resourced vendor in scope, publishing 63 machine-readable models — showed it flags
only ONE of the eight retirements its own deprecation page lists. Until we know whether
that is typical or unusually bad, building a general ingestion layer would be designing
for a yield nobody has measured.

So: one vendor, honestly scoped, producing a REPORT a human reads. It never writes to the
catalog. Everything still enters through `drift-scan absorb`, which requires a source URL
and a parseable date — and a spec carries no date, so a spec alone can never produce a
dated finding.

Network lives here, not in `agent/lib/oas_deprecations.py`, so the parser stays pure and
this cannot be reached from the deterministic auto scan path.
"""
from __future__ import annotations

import json
import urllib.request

from agent.lib import oas_deprecations as oas
from agent.lib.vendor_sunsets import load_sunsets

# The only vendor with a measured, reconciled spec source. Adding a second one is a
# decision informed by that vendor's measured flag coverage — not a copy-paste.
SOURCES = {
    "Amazon SP-API": {
        "tree": ("https://api.github.com/repos/amzn/selling-partner-api-models/"
                 "git/trees/main?recursive=1"),
        "raw": "https://raw.githubusercontent.com/amzn/selling-partner-api-models/main/",
        "match": lambda p: p.startswith("models/") and p.endswith(".json"),
        "page": "https://developer-docs.amazon/sp-api/docs/sp-api-deprecations",
    },
}


def _fetch_json(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "drift-detector"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:    # noqa: S310
        return json.loads(resp.read().decode())


def refresh(vendor: str, *, fetch=None, catalog=None) -> dict:
    """Fetch the vendor's specs and reconcile. `fetch` is injected so this is testable
    without network."""
    src = SOURCES.get(vendor)
    if not src:
        raise KeyError(f"no measured spec source for {vendor!r} — "
                       f"known: {', '.join(sorted(SOURCES))}")
    fetch = fetch or _fetch_json
    tree = fetch(src["tree"])
    paths = [n["path"] for n in (tree.get("tree") or []) if src["match"](n["path"])]

    records, all_paths, failed = [], set(), []
    for p in paths:
        try:
            doc = fetch(src["raw"] + p)
        except Exception as exc:                 # one unreachable model must not read as
            failed.append({"spec": p, "error": str(exc)[:120]})   # "nothing deprecated"
            continue
        records += oas.extract(doc, source=src["raw"] + p)
        all_paths |= {str(k) for k in (doc.get("paths") or {})}

    out = oas.reconcile(records, catalog if catalog is not None else load_sunsets(),
                        vendor, all_spec_paths=all_paths)
    out["specsFetched"] = len(paths) - len(failed)
    out["specsFailed"] = failed
    out["deprecatedOperations"] = records
    out["datesSource"] = src["page"]
    return out


def render(result: dict) -> str:
    """A report, in the terms a reviewer needs to act on."""
    c = result["counts"]
    L = [f"catalog-refresh · {result['vendor']}",
         f"  specs fetched            : {result['specsFetched']}"]
    if result["specsFailed"]:
        L.append(f"  ⚠ specs UNREACHABLE      : {len(result['specsFailed'])} "
                 f"— an unfetched spec is not an unflagged one")
    L += [f"  families flagged in spec : {c['specFamilies']}",
          f"  families in our catalog  : {c['catalogFamilies']}", ""]

    if result["confirmed"]:
        L.append("CONFIRMED — we hold the date, the spec names the exact operations:")
        for fam, ops in sorted(result["confirmed"].items()):
            L.append(f"   {fam:<26} {len(ops)} op(s): {', '.join(ops[:8])}")
        L.append("")
    if result["newlyFlagged"]:
        L.append("NEWLY FLAGGED by the vendor, absent from our catalog "
                 "(UNDATED — needs the deprecation page for a date):")
        for fam, ops in sorted(result["newlyFlagged"].items()):
            L.append(f"   {fam:<26} {len(ops)} op(s): {', '.join(ops[:8])}")
        L.append("")
    if result["specRemoved"]:
        L.append("CORROBORATED — in our catalog, and the spec is gone entirely "
                 "(vendor deletes the model once an API is switched off):")
        L += [f"   {f}" for f in result["specRemoved"]]
        L.append("")
    if result["specUnflagged"]:
        L.append("⚠ CONFLICT — our catalog dates these, but the vendor still publishes "
                 "them with NO deprecated flag.")
        L.append("  The vendor disagrees with itself. Do NOT read this as a clearance; "
                 "verify against the page below.")
        L += [f"   {f}" for f in result["specUnflagged"]]
        L.append("")
    L.append(f"dates come from: {result['datesSource']}")
    L.append("Nothing was written. Stage changes and run `drift-scan absorb`.")
    return "\n".join(L)

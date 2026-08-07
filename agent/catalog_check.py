"""Re-check vendors' live deprecation sources against our catalog — the freshness loop.

A "keep green" scanner whose catalog never re-checks the vendor silently rots: a
retirement announced after we last looked stays invisible until someone re-fetches by
hand. This fetches each vendor's live source and reports what CHANGED — new retirements,
dates the vendor has since moved, or (for Shopify) a computed rule that no longer matches
the published table.

Reports only. Nothing is written: staging + `drift-scan absorb` remain the sole path into
the catalog, so a fetched fact still gets a human's eyes and a sourced date before it is
trusted. Network lives here, never in the deterministic scan path.
"""
from __future__ import annotations

from agent.lib import catalog_sources, catalog_coverage
from agent.lib.vendor_sunsets import load_sunsets

# vendor -> (check kind, source url). Structured, machine-readable sources first; Amazon
# has its own OpenAPI reconciliation (drift-scan catalog-refresh), Walmart's guide is HTML
# and is not yet auto-parsed — both are named in the report so the gaps are explicit.
CHECKS = {
    "eBay": ("diff", catalog_sources.EBAY_RSS_URL),
    "Shopify": ("rule", catalog_sources.SHOPIFY_VERSIONING_MD),
}
UNAUTOMATED = {
    "Amazon SP-API": "run `drift-scan catalog-refresh --vendor \"Amazon SP-API\"` (OpenAPI specs)",
    "Walmart": "re-fetch the deprecation guide by hand — it is server-rendered HTML, not yet auto-parsed",
}


def _default_fetch(url: str) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "drift-detector"})
    with urllib.request.urlopen(req, timeout=60) as r:          # noqa: S310
        return r.read().decode("utf-8", "replace")


def check_all(*, fetch=None, catalog=None, attestations=None, now: str | None = None) -> list:
    fetch = fetch or _default_fetch
    catalog = catalog if catalog is not None else load_sunsets()
    attestations = attestations if attestations is not None else catalog_coverage.load_attestations()
    out = []
    for vendor, (kind, url) in CHECKS.items():
        rec = {"vendor": vendor, "kind": kind, "source": url}
        try:
            text = fetch(url)
            if kind == "diff":
                facts = catalog_sources.parse_ebay_rss(text)
                rec.update(catalog_sources.diff_against_catalog(facts, catalog, vendor))
            else:
                res = catalog_sources.check_shopify_rule(text)
                if res.get("unreadable"):       # parsed nothing — treat as couldn't-check
                    rec["error"] = "could not parse the version table (page format changed?)"
                else:
                    rec.update(res)
        except Exception as exc:                # unreachable source is reported, never a clean pass
            rec["error"] = str(exc)[:200]
        if now:
            verdict, _reasons, checked = catalog_coverage.verdict_for(vendor, attestations, now)
            rec["attestation"] = {"verdict": verdict, "checked": checked}
        out.append(rec)
    return out


def needs_attention(report: list) -> bool:
    """True if any vendor has a new/changed retirement, rule drift, or an unreachable
    source — anything a human should act on."""
    for r in report:
        if r.get("error"):
            return True
        if r.get("kind") == "diff" and (r.get("new") or r.get("changed")):
            return True
        if r.get("kind") == "rule" and r.get("drift"):
            return True
    return False


def render(report: list) -> str:
    L = ["catalog-check · re-checking vendor sources against our catalog", ""]
    for r in report:
        att = r.get("attestation") or {}
        head = f"  {r['vendor']}"
        if att:
            head += f"  [catalog {att.get('verdict')}, checked {att.get('checked') or 'never'}]"
        L.append(head)
        if r.get("error"):
            L.append(f"    ⚠ could not reach the source: {r['error']}")
            L.append(f"    an unreachable source is not a clean check — retry, or verify by hand.")
            continue
        if r["kind"] == "diff":
            c = r["counts"]
            if c["new"]:
                L.append(f"    🆕 {c['new']} NEW retirement(s) the vendor lists that our catalog lacks:")
                for f in r["new"]:
                    L.append(f"        {f['api']} · {f.get('operation')} · retires {f['retires']}")
            if c["changed"]:
                L.append(f"    ✏ {c['changed']} date(s) the vendor has MOVED since we catalogued them:")
                for f in r["changed"]:
                    L.append(f"        {f.get('operation')}: we have {f['catalogRetires']}, vendor now says {f['retires']}")
            if c["undated"]:
                L.append(f"    · {c['undated']} whole-API / TBD item(s) — not scopeable, left uncatalogued")
            if not (c["new"] or c["changed"]):
                L.append(f"    ✓ up to date — {c['covered']} dated retirement(s) all match")
        else:  # rule
            if r.get("ok"):
                L.append(f"    ✓ computed rule still reproduces all {r['rowsChecked']} published rows")
            else:
                L.append(f"    ⚠ RULE DRIFT — the published table no longer matches our computed rule:")
                for d in r.get("drift", []):
                    L.append(f"        {d['version']}: vendor says {d['accessibleUntil']}, rule computes {d['ruleSays']}")
    L.append("")
    for vendor, how in UNAUTOMATED.items():
        L.append(f"  {vendor}: not auto-checked — {how}")
    L.append("")
    L.append("Nothing was written. Stage any change and run `drift-scan absorb`.")
    return "\n".join(L)

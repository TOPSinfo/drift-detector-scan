"""Parse vendors' LIVE deprecation sources into normalized retirement facts.

The freshness half of the catalog: `agent/catalog_check.py` fetches these sources on demand
and diffs the facts against `agent/vendor_sunsets.yaml`, so a retirement the vendor
announced AFTER we last checked shows up as a gap instead of silently ageing. A "keep
green" scanner whose catalog never re-checks the vendor is exactly the failure this closes.

Parsers are PURE (text in, facts out) so they test against committed fixtures with no
network; fetching lives in the caller and never runs in the deterministic scan path. A
date the vendor didn't state is never invented here — an item without a decommission date
becomes a dateless fact, not a guessed one.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

EBAY_RSS_URL = "https://www.edp.ebay.com/rss/api-deprecation"


def _text(el, tag: str) -> str:
    node = el.find(tag)
    if node is None:
        return ""
    return html.unescape("".join(node.itertext())).replace("\xa0", " ").strip()


_DATE = re.compile(r"(\d{4})[/-](\d{2})[/-](\d{2})")


def _norm_date(s: str) -> str | None:
    """eBay writes YYYY/MM/DD; normalise to YYYY-MM-DD. 'TBD' / blank -> None (undated)."""
    m = _DATE.search(str(s or ""))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def parse_ebay_rss(xml_text: str) -> list:
    """eBay's structured deprecation feed -> one fact per (api, method).

    Each <item> carries <title> (the API), <methods><method>, <deprecationDate>,
    <decommissionDate> (the sunset), and <notes>. A method of 'All' or an item with no
    methods is a WHOLE-API deprecation — kept as an operation-less fact, because it cannot
    be scoped to a call-site the way a named method can.
    """
    root = ET.fromstring(xml_text)
    out = []
    for it in root.findall(".//item"):
        api = _text(it, "title")
        retires = _norm_date(_text(it, "decommissionDate"))
        deprecated = _norm_date(_text(it, "deprecationDate"))
        methods = [("".join(m.itertext())).strip() for m in it.findall(".//method")]
        methods = [m for m in methods if m]
        if not methods or methods == ["All"]:
            out.append({"vendor": "eBay", "api": api, "operation": None,
                        "retires": retires, "deprecated": deprecated, "source": EBAY_RSS_URL})
        else:
            for m in methods:
                out.append({"vendor": "eBay", "api": api, "operation": m,
                            "retires": retires, "deprecated": deprecated,
                            "source": EBAY_RSS_URL})
    return out


# The human page is a JS shell; the `.md` twin returns the same content as clean markdown
# (any shopify.dev page + .md). Fetch the .md; cite the human page.
SHOPIFY_VERSIONING_URL = "https://shopify.dev/docs/api/usage/versioning"
SHOPIFY_VERSIONING_MD = "https://shopify.dev/docs/api/usage/versioning.md"
_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
           "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
           "december": 12}
_ACCESSIBLE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})")   # "July 16, 2026"


def parse_shopify_versions(md_text: str) -> list:
    """Shopify's published support table -> [{version, accessibleUntil (YYYY-MM-DD)}].

    Shopify is COMPUTED, not curated — freshness means checking that our rule still
    reproduces this table. A parser, not a diff-against-catalog, because there are no
    Shopify catalog entries to diff."""
    out = []
    for line in md_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not re.match(r"^\d{4}-\d{2}$", cells[0]):
            continue
        m = _ACCESSIBLE.search(cells[2])
        if not m:
            continue
        mon = _MONTHS.get(m.group(1).lower())
        if not mon:
            continue
        out.append({"version": cells[0],
                    "accessibleUntil": f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"})
    return out


def check_shopify_rule(md_text: str) -> dict:
    """Does our computed rule still reproduce Shopify's published table? If Shopify ever
    changes the support window, this drifts — and a computed feeder that has silently gone
    wrong is worse than a missing one."""
    from agent.lib.version_lifecycle import shopify_sunset
    rows = parse_shopify_versions(md_text)
    # Zero rows means we could not READ the table (page format changed, wrong URL) — NOT
    # that the rule is fine and NOT that it drifted. Conflating "unreadable" with either is
    # how a freshness check silently lies. It's its own state.
    if not rows:
        return {"vendor": "Shopify", "rowsChecked": 0, "drift": [], "unreadable": True,
                "ok": False, "source": SHOPIFY_VERSIONING_URL}
    drift = [{**r, "ruleSays": shopify_sunset(r["version"])}
             for r in rows if shopify_sunset(r["version"]) != r["accessibleUntil"]]
    return {"vendor": "Shopify", "rowsChecked": len(rows), "drift": drift,
            "unreadable": False, "source": SHOPIFY_VERSIONING_URL, "ok": not drift}


def diff_against_catalog(facts: list, catalog: list, vendor: str) -> dict:
    """Compare live vendor facts against our catalog entries for one vendor.

    Buckets, each actionable:
      new      the vendor lists a dated, scopeable retirement our catalog does not have
      changed  we have the entry but our date disagrees with the vendor's now
      covered  we have it and the dates agree
      undated  vendor lists it but with no decommission date (TBD) — cannot be catalogued
    Returns data; nothing is written. Staging + the absorb gate remain the only way in.
    """
    by_op = {}
    for e in catalog:
        if e.get("vendor") == vendor and e.get("operation"):
            by_op[e["operation"]] = e
    new, changed, covered, undated = [], [], [], []
    for f in facts:
        op = f.get("operation")
        if not op:                                   # whole-API, not scopeable -> report
            undated.append(f)
            continue
        if not f.get("retires"):
            undated.append(f)
            continue
        have = by_op.get(op)
        if not have:
            new.append(f)
        elif str(have.get("retires")) != f["retires"]:
            changed.append({**f, "catalogRetires": have.get("retires")})
        else:
            covered.append(f)
    return {"vendor": vendor, "new": new, "changed": changed,
            "covered": covered, "undated": undated,
            "counts": {"new": len(new), "changed": len(changed),
                       "covered": len(covered), "undated": len(undated)}}

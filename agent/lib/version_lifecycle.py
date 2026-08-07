"""Computed retirement dates for vendors with a PUBLISHED, RULE-BASED version lifecycle.

Most vendor retirements are one-off announcements a human curates (Amazon, eBay). A few
vendors instead publish a RULE that dates every version deterministically — so the catalog
does not need one hand-fetched entry per version, and it never goes stale as new versions
ship. Shopify is the motivating case.

SHOPIFY. Versions are calendar-quarterly (`2024-01`, `2024-04`, …). The versioning page
states: "Each stable version is supported for a minimum of 12 months, with at least nine
months of overlap." The published support table shows the exact pattern, verified against
all seven listed rows (fetched 2026-07-21):

    version YYYY-MM  released YYYY-MM-01  accessible until (YYYY+1)-MM-16 15:00 UTC

So a version's sunset is computed, not curated: `2024-01` → `2025-01-16`. The RULE is the
source (the versioning page), not a per-version date nobody fetched — which is what keeps
this inside the never-invent-a-date discipline. The published table is the authoritative
CROSS-CHECK (a test asserts the rule reproduces all seven rows); the rule's own guarantee
is only a *minimum* 12 months, so if Shopify ever extends a window the table wins.

One behavioural nuance that changes the advice: Shopify does NOT error on a retired
version — it "falls forward" and silently serves the oldest accessible version. So a dead
version is silent behavioural drift, not a 4xx, which is worse to leave unnoticed.

Pure and deterministic: string in, date string out. No I/O.
"""
from __future__ import annotations

import re

SHOPIFY_SOURCE = "https://shopify.dev/docs/api/usage/versioning"
_YYYY_MM = re.compile(r"^(\d{4})-(\d{2})$")


def shopify_sunset(version: str) -> str | None:
    """The 'accessible until' date for a Shopify version `YYYY-MM`, or None if the string
    is not a Shopify calendar version. Release is the 1st of the month; the window is
    +12 months +15 days (the 16th of the same month, one year on)."""
    m = _YYYY_MM.match(str(version or ""))
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        return None
    return f"{year + 1:04d}-{month:02d}-16"


# vendor -> (sunset_rule, source_url, replacement_hint). The audit consults this for any
# endpoint whose vendor appears here and whose version the rule can date.
LIFECYCLE_RULES = {
    "Shopify": (shopify_sunset, SHOPIFY_SOURCE,
                "bump the API version — a retired version is not an error, Shopify "
                "silently serves the oldest accessible version (behavioural drift)"),
}


def lifecycle_sunset(vendor: str, version: str):
    """(retires, source, replacement) for a vendor+version under a lifecycle rule, or
    None when the vendor has no rule or the version is not datable by it."""
    rule = LIFECYCLE_RULES.get(vendor)
    if not rule:
        return None
    fn, source, replacement = rule
    retires = fn(version)
    if not retires:
        return None
    return {"retires": retires, "source": source, "replacement": replacement}

"""endoflife.date client — is a runtime/framework version end-of-life (or nearing it)?

https://endoflife.date/api/{product}.json -> [{cycle, eol, latest, lts, ...}].
HTTP is injected (see http_util). Classifies to DEPRECATED / REVIEW / OK.
"""
from __future__ import annotations

from datetime import date, timedelta

from agent.lib.http_util import default_http

# our runtime/framework name -> endoflife.date product slug (None = not tracked, skip)
PRODUCT_MAP = {
    "node": "nodejs", "php": "php", "python": "python",
    "laravel/framework": "laravel", "next": "nextjs", "vue": "vue",
    "django": "django", "symfony/framework-bundle": "symfony",
    # Magento / Adobe Commerce software EOL (endoflife.date/magento tracks 2.4.4..2.4.9).
    # NOTE: this is the SERVER's version — it only surfaces when a Magento INSTALL is scanned
    # (its composer.json requires the package). A wrapper that merely CALLS Magento's REST API
    # never pins this, so it does not fire on integration-client repos.
    "magento/product-community-edition": "magento",
    "magento/product-enterprise-edition": "magento",
    "magento/magento2-base": "magento",
}

_REVIEW_WINDOW = timedelta(days=183)   # "EOL within ~6 months" -> REVIEW (per the original design)


def product_slug(name: str) -> str | None:
    return PRODUCT_MAP.get(name)


def _match_cycle(cycles: list, version: str) -> dict | None:
    # most specific cycle that prefixes the version (e.g. "8.2" for "8.2.0")
    pref = [c for c in cycles if version == str(c.get("cycle")) or version.startswith(str(c.get("cycle")) + ".")]
    if pref:
        return max(pref, key=lambda c: len(str(c.get("cycle"))))
    major = version.split(".")[0]                     # fall back to major line ("15" for "15.14.0")
    for c in cycles:
        if str(c.get("cycle")) == major:
            return c
    return None


def _classify(eol, now: date):
    if eol is True:
        return "DEPRECATED", None
    if eol is False or eol is None:
        return "OK", None
    try:
        eol_date = date.fromisoformat(str(eol))
    except ValueError:
        return "OK", None
    if eol_date <= now:
        return "DEPRECATED", eol_date.isoformat()
    if eol_date <= now + _REVIEW_WINDOW:
        return "REVIEW", eol_date.isoformat()
    return "OK", eol_date.isoformat()


def check(product: str, version: str | None, now: str, *, http=default_http) -> dict | None:
    """Return {product, slug, cycle, status, eol_date, latest, source_url} or None if untracked/unknown."""
    slug = product_slug(product)
    if not slug or not version:
        return None
    cycles = http(f"https://endoflife.date/api/{slug}.json")
    cyc = _match_cycle(cycles, version)
    if not cyc:
        return None
    today = date.fromisoformat(now)
    status, eol_date = _classify(cyc.get("eol"), today)
    return {
        "product": product, "slug": slug, "cycle": str(cyc.get("cycle")),
        "status": status, "eol_date": eol_date, "latest": cyc.get("latest"),
        "recommended": _newest_supported(cycles, today),
        "source_url": f"https://endoflife.date/{slug}",
    }


def _newest_supported(cycles: list, now: date) -> str | None:
    # sensible upgrade target: prefer a fully-supported (OK) cycle; fall back to one
    # merely nearing EOL (REVIEW) over nothing. endoflife.date lists cycles newest-first.
    review = None
    for c in cycles:
        status = _classify(c.get("eol"), now)[0]
        target = str(c.get("latest") or c.get("cycle"))
        if status == "OK":
            return target
        if status == "REVIEW" and review is None:
            review = target
    return review

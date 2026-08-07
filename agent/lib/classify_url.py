"""Classify a discovered URL against the vendor catalog (discover-then-classify).

The scan now finds ALL http(s) URL literals; this decides what each one is:
- a KNOWN vendor (registrable-domain suffix match, e.g. `ebay.com` matches `api.sandbox.ebay.com`;
  or a distinctive host fragment like `sellingpartnerapi` for regional Amazon SP-API hosts),
- boilerplate to IGNORE (schemas, w3.org, localhost, fonts, analytics — not integrations),
- otherwise an UNKNOWN external endpoint (surfaced so the catalog is never the ceiling).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from agent.lib.vendors import DEFAULT_VERSION_REGEX

_URL_RE = re.compile(r"""https?://[^\s"'`<>)\]}]+""", re.IGNORECASE)

# hosts (by registrable suffix) that are never third-party API integrations
_IGNORE = {
    # schemas / specs / xml namespaces
    "w3.org", "xmlsoap.org", "schema.org", "json-schema.org", "purl.org", "apache.org",
    "example.com", "example.org", "example.net", "localhost", "test.com", "gmpg.org",
    # asset / font / image CDNs + placeholders
    "fonts.googleapis.com", "fonts.gstatic.com", "gstatic.com", "jsdelivr.net", "unpkg.com",
    "cloudflare.com", "cdnjs.cloudflare.com", "bootstrapcdn.com", "fonts.bunny.net",
    "gravatar.com", "placeholder.com", "placehold.co", "picsum.photos", "via.placeholder.com",
    # analytics / tag managers
    "googletagmanager.com", "google-analytics.com", "ns.adobe.com",
    # developer docs / package registries / code hosting (repo & doc links, not API calls)
    "github.com", "gitlab.com", "bitbucket.org", "laravel.com", "laracasts.com", "symfony.com",
    "php.net", "npmjs.com", "packagist.org", "wordpress.org", "readthedocs.io", "mozilla.org",
    "getcomposer.org", "nodejs.org", "python.org", "jquery.com", "getbootstrap.com",
    # search / social / video (marketing links, not integrations)
    "google.com", "bing.com", "youtube.com", "youtu.be", "vimeo.com", "facebook.com",
    "twitter.com", "linkedin.com", "instagram.com",
    # front-end libraries / editors / icon sets / placeholders (not service integrations)
    "jqueryui.com", "popper.js.org", "ckeditor.com", "cksource.com", "feathericons.com",
    "placehold.jp", "kwcdn.com",
    # XML/spec namespaces + vendor STATIC-asset hosts (images/CSS, not the vendor's API)
    "iso.org", "macromedia.com", "ebaystatic.com",
}

# A syntactically valid host: >=2 non-empty labels of [a-z0-9_-]. Catches URL-extraction
# artifacts that reach here as bogus "hosts" — "...", "sandbox.", "ckeditor.com\x3c".
_LABEL = re.compile(r"^[a-z0-9_-]+$", re.IGNORECASE)


def extract_urls(text: str) -> list:
    return _URL_RE.findall(text or "")


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_ignored(host: str) -> bool:
    if not host or "." not in host or host.replace(".", "").isdigit():   # empty / bare / raw IP
        return True
    labels = host.split(".")
    if len(labels) < 2 or any(not _LABEL.match(lab) for lab in labels):  # extraction artifact
        return True
    return any(host == s or host.endswith("." + s) for s in _IGNORE)


_HOSTCHAR = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")


def _at_boundary(text: str, token: str) -> bool:
    """`token` occurs in `text` starting at a label boundary (not mid-label), so `ups.com`
    matches `.ups.com`/start but NOT `startups.com`, and `sellingpartnerapi` doesn't match
    `notsellingpartnerapi…`."""
    start = 0
    while True:
        i = text.find(token, start)
        if i < 0:
            return False
        if i == 0 or text[i - 1] not in _HOSTCHAR:
            return True
        start = i + 1


def _matches(host: str, domain: str) -> bool:
    d = domain.lower()
    if "." in d:
        return host == d or host.endswith("." + d)      # registrable-domain suffix
    return _at_boundary(host, d)                         # distinctive fragment (e.g. sellingpartnerapi)


def classify_host(host: str, vendors: list):
    """Return the best-matching Vendor (most specific domain wins) or None."""
    best, best_len = None, -1
    for v in vendors:
        for d in v.domains:
            if _matches(host, d) and len(d) > best_len:
                best, best_len = v, len(d)
    return best


def version_of(url: str, vendor) -> str | None:
    regex = vendor.version_regex if vendor else DEFAULT_VERSION_REGEX
    m = re.search(regex, url)
    return m.group(1) if m else None


def path_signature_match(text: str, vendors: list):
    """The (vendor, version, sample) for the first vendor whose `path_signature` matches
    `text`, or None. Host-INDEPENDENT: for calls whose host is a runtime variable —
    `Http::…->get("https://{$shop}/admin/api/2024-01/shop.json")` — the interpolation
    truncates URL extraction and host classification is blind, but the `/admin/api/{version}/`
    path is unmistakably Shopify. Group 1 of the signature is the version (None if absent).
    Most specific (longest match) wins so overlapping signatures resolve deterministically."""
    best, best_span = None, -1
    for v in vendors:
        if not v.path_signature:
            continue
        m = re.search(v.path_signature, text or "")
        if m and (m.end() - m.start()) > best_span:
            ver = m.group(1) if m.groups() else None
            best, best_span = (v, ver, m.group(0)), m.end() - m.start()
    return best


def domain_in_line(line: str, domains) -> str:
    # host-boundary aware so `ups.com` doesn't fire on `startups.com` / `groups.company.com`
    for d in domains:
        if _at_boundary(line, d):
            return d
    return ""


# YYYY-MM-DD (Amazon SP-API) is tried before YYYY-MM (Shopify's quarterly calendar
# versions, e.g. /admin/api/2024-01/) so the longer full-date match always wins.
_VERSION_SEG = re.compile(r"/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{4}-[0-9]{2})(/|$)")

# An API OPERATION name — the unit some vendors deprecate independently of the host.
# eBay's Trading API is the motivating case: one host (api.ebay.com), one path
# (/ws/api.dll), ~19 operations on separate lifecycles, so (vendor, host, version)
# cannot distinguish "GetCategories is dead" from "GetItem is alive". Two marker
# shapes carry the name at the call-site:
#   • the XML request root  -> <GetCategoryFeaturesRequest xmlns="urn:ebay:apis:...">
#   • the call-name argument -> getEbaySession("GetCategories", ...)  (becomes the
#     X-EBAY-API-CALL-NAME header)
_OP_XML_ROOT = re.compile(r"<([A-Z][A-Za-z0-9]{2,})Request\b")
_OP_CALL_NAME = re.compile(r"""(?:CALL-NAME|getEbaySession)\s*[:(]\s*['"]([A-Z][A-Za-z0-9]{2,})['"]""")


def operation_of(line: str) -> str:
    """The API operation named on `line`, or '' if none. Never guesses: the name
    must appear as an XML request root or an explicit call-name argument."""
    m = _OP_XML_ROOT.search(line) or _OP_CALL_NAME.search(line)
    return m.group(1) if m else ""


def api_path_of(s: str) -> str:
    """The API-family prefix of a path or URL, anchored on its version segment:
    '/products/fees/v0/listings/{SellerSKU}/feesEstimate' -> '/products/fees/v0'
    '/v3/insights/refunds'                                -> '/v3/insights/refunds'

    Amazon retires SP-API per (family, version), not per version: `/fba/inbound/v0` died
    2025-01-21 and `/finances/v0` lives until 2027-08-27. Both are "v0", so a catalog
    entry scoped on the version alone would tag every v0 call-site with one date and
    invent most of them. The retiring unit has to be expressible.

    Two URL conventions carry the family differently, and both must survive:
      • version DEEP in the path (Amazon `/products/fees/v0/…`): the family is everything
        UP TO the version — stop there.
      • version FIRST (Walmart `/v3/insights/refunds`): `/v3` alone is every Walmart call,
        so the family is what FOLLOWS the version — extend through static segments,
        stopping at a path parameter. Without this, /v3/insights/refunds and /v3/feeds
        collapse into one `/v3` record and cannot be scoped apart.
    Returns '' when there is no version segment to anchor on.
    """
    s = str(s or "")
    if "://" in s:                                  # drop scheme + host
        s = "/" + s.split("://", 1)[1].partition("/")[2]
    norm = (s if s.startswith("/") else "/" + s).split("?")[0].split("#")[0]
    m = _VERSION_SEG.search(norm)
    if not m:
        return ""
    base = norm[:m.end(1)]
    if m.start() == 0:                              # front-loaded version → extend
        for seg in norm[m.end(1):].split("/")[:6]:  # cap depth; stop at a path parameter
            if not seg:
                continue
            if seg.startswith("{") or seg.startswith(":"):
                break
            base += "/" + seg
    return base


def path_literal_of(line: str) -> str:
    """The first quoted string on `line` that is a version-bearing resource path
    ('/orders/2026-01-01/orders'). Excludes full URLs (those go through the url path).

    A leading slash is NOT required. Requiring one silently dropped every literal
    written as "post-order/v2/cancellation" — the engine matched them, this returned
    "", and they then appeared in neither attribution NOR residue. Invisible, not
    merely unattributed, which is the exact failure the coverage verdict exists to
    make impossible. The version segment is what identifies a resource path; the
    leading slash is just one house style.
    """
    for m in re.finditer(r"""['"]([^'"\s]*/[^'"]*)['"]""", line):
        s = m.group(1)
        if "://" in s:
            continue
        if _VERSION_SEG.search("/" + s.lstrip("/")):
            return s
    return ""


def segment_at(line: str, token: str) -> str:
    """The literal token containing `token` (up to the next quote/space/backtick) — so version/example
    for a host-only reference aren't contaminated by neighbouring text on the line."""
    idx = line.find(token)
    if idx < 0:
        return token
    return re.split(r"""["'\s`]""", line[idx:], 1)[0]

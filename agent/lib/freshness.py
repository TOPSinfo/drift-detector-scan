"""The maintainer FRESHNESS work-order — which catalogued vendors need a human re-check, and
exactly what to fetch for each. The human-lane twin of `catalog_check` (the auto lane).

`catalog_check` re-fetches the vendors with machine-readable public sources (eBay, Shopify).
This covers the rest: a vendor we DETECT whose retirement audit is STALE or never done, and
that the auto lane can't reach. It tells the maintainer the RIGHT action per vendor — a CLI
refresh, a public changelog to read, or a behind-login portal to log into — instead of
assuming. The freshness agent (`/drift-refresh`) drives the loop; the human only supplies what
automation can't: portal access.

Pure and deterministic: coverage records in, work-order out. No I/O, no network.
"""
from __future__ import annotations

# action per vendor:
CLI = "cli"          # a public spec exists but isn't auto-diffed — run a catalog-refresh command
PUBLIC = "public"    # public deprecation docs — no login; read the changelog page
PORTAL = "portal"    # behind a seller-portal login — HIL fetch
UNMAPPED = "unmapped"  # we don't yet know where this vendor publishes deprecations — find out

# Curated freshness recipe: where a vendor publishes deprecations, so the work-order gives the
# RIGHT instruction rather than guessing. A `source` URL appears ONLY where VERIFIED (never a
# guessed source). A vendor absent here is UNMAPPED — the work-order says "find where it
# publishes", not "log into a portal". (kind, source, note)
_RECIPES = {
    # gated — behind a seller-portal login (verified 2026-07-29)
    "THE ICONIC": (PORTAL, "https://sellercenter-api.theiconic.com.au/docs/", "sign-in required"),
    "MyDeal":     (PORTAL, "https://sellerhelp.mydeal.com.au/", "API docs provided on request"),
    "TheMarket":  (PORTAL, "", "no public docs — via seller onboarding"),
    # public — no login; read the changelog page (verified public 2026-07-29)
    "Kogan":      (PUBLIC, "https://developers.kogan.com/changelog",
                   "JS-rendered, relative dates — nothing catalogable as of 2026-07-29"),
    # public — well-known public deprecation docs (the classification is general knowledge; the
    # exact source URL is confirmed at catalog time, not guessed here, so it is left blank)
    "Amazon AWS":    (PUBLIC, "", "AWS service deprecations — public docs"),
    "Amazon MWS":    (PUBLIC, "", "MWS is retired platform-wide — migrate to SP-API"),
    "Google APIs":   (PUBLIC, "", "public deprecation schedule"),
    "Google OAuth2": (PUBLIC, "", "public deprecation schedule"),
    "Mailgun":       (PUBLIC, "", "public API docs"),
}


def _classify(vendor: str, unautomated: dict):
    """(action, source, note) for a vendor on the human lane."""
    if vendor in unautomated:
        return CLI, "", unautomated[vendor]
    return _RECIPES.get(vendor, (UNMAPPED, "", ""))


def due_for_refresh(coverage_records: list, auto: set, unautomated: dict) -> list:
    """Vendors needing a HUMAN freshness action: verdict != CURRENT and NOT on the auto lane.
    Each row keeps its coverage fields and gains `action`/`recipeSource`/`recipeNote`.
    Order is inherited from coverage.build (unaudited before stale, then by exposure)."""
    due = []
    for r in coverage_records:
        if r.get("verdict") == "CURRENT":
            continue                       # freshly checked — nothing to do
        if r.get("vendor") in auto:
            continue                       # catalog_check re-fetches this one automatically
        action, source, note = _classify(r.get("vendor"), unautomated)
        due.append({**r, "action": action, "recipeSource": source, "recipeNote": note})
    return due


def _line(r: dict) -> str:
    v, sites, verdict, action = r["vendor"], r.get("callSites", 0), r.get("verdict"), r["action"]
    aged = f", last checked {r['checked']}" if r.get("checked") else ""
    src, note = r.get("recipeSource"), r.get("recipeNote")
    tail = f" — {note}" if note else ""
    if action == CLI:
        todo = note or "run its catalog-refresh command"
        tail = ""                                        # the note IS the instruction for CLI
    elif action == PUBLIC:
        todo = "read the public changelog/deprecation page" + (f" ({src})" if src else "") \
               + " for any \"vX retired DATE\""
    elif action == PORTAL:
        todo = "log into the seller portal" + (f" (start at {src})" if src else "") \
               + ", open the changelog, paste any \"vX retired DATE\" notice + its URL"
    else:  # UNMAPPED
        todo = "find where this vendor publishes deprecations (public page or portal) — not yet mapped"
    return f"- **{v}** — {verdict}{aged}, {sites} call-site(s). {todo}{tail}"


_SECTIONS = [
    (PORTAL, "## Behind a login — needs you (HIL)",
     "Get the material from the seller portal; the agent turns it into a sourced catalog entry:"),
    (PUBLIC, "## Public docs — no login",
     "A public changelog exists; read it (or wire it into `catalog-check` later):"),
    (CLI, "## A command away — no login",
     "A public spec exists; run the noted refresh:"),
    (UNMAPPED, "## Not yet mapped",
     "We don't know where these publish deprecations — map each before it can be re-checked:"),
]


def work_order_md(due: list, now: str) -> str:
    """The maintainer freshness work-order body (a `drift:freshness` issue), grouped by the
    action each vendor needs. Every path ends at `absorb`, so a wrong/invented date is refused
    and a clean gate attests the vendor CURRENT (resetting its staleness clock)."""
    if not due:
        return "# Catalog freshness\n\nNothing due — every detected vendor is CURRENT.\n"
    L = [f"# Catalog freshness — {len(due)} vendor(s) due (as of {now})", "",
         "The scanner detects these vendors but their retirement audit is **STALE or "
         "unaudited**, and the auto lane can't refresh them. Do the action noted for each, then "
         "the next scan stops treating \"0 findings\" here as clean.", ""]
    for action, heading, blurb in _SECTIONS:
        rows = [r for r in due if r["action"] == action]
        if rows:
            L += [heading, blurb, ""] + [_line(r) for r in rows] + [""]
    L += ["## The rails (why this is safe)",
          "Run **`/drift-refresh`** and paste what you gather. Every proposed retirement goes "
          "through `drift-scan absorb`: no `source` + parseable date → **refused** (a borrowed "
          "or invented date is worse than none). A clean gate promotes the entry to the drift-ops "
          "overlay and attests the vendor **CURRENT** — resetting its staleness clock.",
          "",
          "**Reviewed the page and found nothing dated?** That is a real outcome, not a "
          "failure: record it as an attestation (`{vendor, checked: <fetch date>, source: <the "
          "page>, note: \"nothing dated to catalog\"}` in the drift-ops overlay's "
          "`attestations.local.yaml`) so the vendor goes CURRENT and stops re-surfacing every "
          "cycle — zero catalog entries and a zero-retirement page AGREE, which is exactly what "
          "an attestation claims. Only after the canonical page was actually read in full "
          "(rendered, if it's a JS page a plain fetch can't read) — \"the fetch showed nothing\" "
          "is not \"the page says nothing\".", ""]
    return "\n".join(L)

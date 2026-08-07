"""Read vendor-published OpenAPI specs for `deprecated: true` — structured, no judgement.

WHY THIS TIER EXISTS. Vendor API retirements are the only audit tier with no live source:
CVEs come from OSV.dev, runtime EOL from endoflife.date, and vendor sunsets from a YAML
somebody hand-edits. But vendors DO publish machine-readable deprecation state — they just
publish it in their API specs rather than in a feed.

WHAT THIS TIER CAN AND CANNOT ANSWER. Verified on Amazon's own models:

    spec says  getOrders GET /orders/v0/orders  "deprecated": true    <- WHAT, precisely
    spec says  (nothing about a retirement date)                      <- WHEN, never

and the human deprecation page is the mirror image: it carries dates but only names
families ("Orders v0", "Fulfillment Inbound v0 (multiple operations)" — without saying
which operations). So a spec CANNOT produce a dated finding on its own, and this module
does not pretend otherwise: it emits `deprecated-no-date` records, which the catalog
already models as a first-class state.

The two tiers are complementary and are meant to be reconciled by a human, not merged
automatically. When they disagree — spec flags an operation the page never mentions, or
the page dates something the spec calls live — that is a CONFLICT to surface, not a tie to
break silently. Silently picking is how a wrong date enters an audit people escalate on.

Pure and deterministic: parses a dict, does no I/O. Fetching lives in the caller so this
is testable without network and cannot run in the auto scan path by accident.
"""
from __future__ import annotations

_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")


def _server_prefix(doc: dict) -> str:
    """The path prefix a server URL contributes, e.g. '/sp-api' — usually empty."""
    for s in (doc.get("servers") or []):
        url = str(s.get("url") or "")
        if "://" in url:
            rest = url.split("://", 1)[1]
            path = "/" + rest.partition("/")[2]
            return path.rstrip("/") if path != "/" else ""
    base = str(doc.get("basePath") or "")          # OpenAPI 2.0 / Swagger
    return base.rstrip("/")


def extract(doc: dict, *, source: str = "") -> list:
    """Every deprecated operation in an OpenAPI 2.0/3.x document.

    Returns [{path, method, operationId, apiPath, title, apiVersion, source}], sorted for
    determinism. `deprecated` may sit on the operation OR on the path item (applying to
    every method under it); both are honoured, because missing the path-item form would
    silently under-report — the failure mode this project keeps guarding against.
    """
    if not isinstance(doc, dict):
        return []
    from agent.lib.classify_url import api_path_of

    info = doc.get("info") or {}
    title, version = str(info.get("title") or ""), str(info.get("version") or "")
    prefix = _server_prefix(doc)

    out = []
    for raw_path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        full = prefix + str(raw_path)
        path_level = bool(item.get("deprecated"))
        for method in _METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            if not (path_level or op.get("deprecated")):
                continue
            out.append({
                "path": full,
                "method": method.upper(),
                "operationId": str(op.get("operationId") or ""),
                # the API-family prefix the catalog scopes on, e.g. /orders/v0
                "apiPath": api_path_of(full),
                "title": title,
                "apiVersion": version,
                "source": source,
            })
    out.sort(key=lambda r: (r["apiPath"], r["path"], r["method"]))
    return out


def group_by_family(records: list) -> dict:
    """{apiPath: [operationId, …]} — the shape the catalog scopes on, so a spec result can
    be compared against a `path:`-scoped entry directly."""
    fam: dict = {}
    for r in records:
        fam.setdefault(r["apiPath"], []).append(r["operationId"] or f'{r["method"]} {r["path"]}')
    return {k: sorted(set(v)) for k, v in sorted(fam.items())}


def reconcile(spec_records: list, catalog_entries: list, vendor: str,
              *, all_spec_paths: set | None = None) -> dict:
    """Compare what the vendor's specs flag against what our catalog claims.

    FOUR buckets, because "our entry is not flagged in the spec" turned out to mean two
    opposite things. Measured against Amazon's 63 published models on 2026-07-20:

      confirmed     catalog has a DATE, spec confirms the deprecation and names the exact
                    operations. Strictly better than either source alone. (1 of 8)
      newlyFlagged  spec flags a family our catalog never heard of. Undated — it cannot
                    become a dated finding — but it is a real work-list. (0 of 8)
      specRemoved   the family appears in NO published spec. Amazon deletes a model once
                    the API is switched off, so absence CORROBORATES our dated entry
                    rather than contradicting it. (3 of 8: reports/feeds 2020-09-04,
                    fba/smallAndLight/v1)
      specUnflagged the family is still published and carries NO deprecated flag, while
                    the vendor's own deprecation PAGE says it retired. The vendor
                    contradicts itself. (4 of 8: fba/inbound/v0, catalog/v0, mfn/v0,
                    finances/v0 — including one Amazon says stopped working 2025-01-21)

    That last bucket is why nothing here is automatic. Read naively — "not flagged means
    not deprecated" — a refresh would have proposed deleting seven of our eight entries,
    six of them for APIs that are genuinely dead. A vendor's machine-readable source is
    evidence, not truth, and where two of its own channels disagree only a human can say
    which to believe.

    Returns data, never a mutation. Nothing enters the catalog except through absorb.
    """
    spec_families = group_by_family(spec_records)
    cat_families = {str(e.get("path")) for e in catalog_entries
                    if e.get("vendor") == vendor and e.get("path")}

    confirmed, newly = {}, {}
    for fam, ops in spec_families.items():
        (confirmed if fam in cat_families else newly)[fam] = ops

    unmatched = sorted(cat_families - set(spec_families))
    removed, unflagged = [], []
    for fam in unmatched:
        if all_spec_paths is None:
            unflagged.append(fam)          # cannot distinguish without the full path set
        elif any(p.startswith(fam) for p in all_spec_paths):
            unflagged.append(fam)          # still published, just not flagged -> conflict
        else:
            removed.append(fam)            # gone from the specs -> corroborates removal
    return {"vendor": vendor, "confirmed": confirmed, "newlyFlagged": newly,
            "specRemoved": removed, "specUnflagged": unflagged,
            "counts": {"specFamilies": len(spec_families),
                       "catalogFamilies": len(cat_families),
                       "confirmed": len(confirmed), "newlyFlagged": len(newly),
                       "specRemoved": len(removed), "specUnflagged": len(unflagged)}}

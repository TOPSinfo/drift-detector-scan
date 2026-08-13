"""The coverage tree — one structure, rendered twice.

The cockpit used to headline a strip of tiles whose numbers did not sum: `Tracked` counted
distinct VENDORS while `Detected`/`Queued`/`Assets` counted endpoint ROWS, so the row read
21 + 3 + 43 against a Detected of 73, with nothing on screen declaring the unit change.

This computes the breakdown ONCE, in Python, from the canonical payload. `md_tree` and
`html_tree` are thin renderers over it, so the Markdown and the dashboard cannot disagree, and
`verify` checks each against `drift.json` rather than against each other — the same contract
every other surface in this tool meets.

Every node counts ROWS. The distinct-vendor figure is real and useful, but it is a different
unit, so it rides on `tracked` as an annotation rather than becoming a sibling that breaks the
arithmetic.

Pure: a dict in, a list out. No I/O, no clock.
"""
from __future__ import annotations

from collections import Counter

# Assets are grouped by hostClass. This is an ORDERING preference, not a filter: classes
# listed here render first, in this order, because they are the biggest/most familiar
# buckets. Any hostClass NOT in this tuple still becomes a child — it is appended after,
# alphabetically — because a filter silently drops rows it doesn't recognise, and this
# structure's whole reason for existing is that its children always sum to their parent.
_ASSET_CLASSES = ("boilerplate", "social-widget", "vendored-lib", "asset-cdn", "own-infra",
                  "analytics")

_LABELS = {
    "detected": "detected", "integrations": "integrations", "assets": "assets",
    "tracked": "tracked", "queued": "queued", "needs-human": "needs human", "blocked": "blocked",
}


def _node(key, n, *, note="", children=None, unit="rows"):
    return {"key": key, "label": _LABELS.get(key, key), "n": n, "unit": unit,
            "note": note, "children": children or []}


def build(payload: dict) -> list:
    """The node tree for `payload`. One root (`detected`); children sum to their parent.

    A count that cannot be derived is None with a `note` saying why — never 0, because a
    confident zero over missing data is the exact failure this tool exists to refuse.
    """
    counts = payload.get("counts") or {}
    cov = counts.get("coverage")
    # The asset breakdown comes from the ENDPOINT ROWS, never from counts.hostClasses.
    # hostClasses tallies all 73 endpoints, so its asset-class entries sum to 45 against an
    # assets total of 43: a token-claimed `own-infra` row is kept QUEUED (it might be a real
    # third party), which makes it an integration, not an asset. Deriving from hostClasses
    # would put the tree out by exactly that difference — the arithmetic failure this tree
    # exists to make impossible.
    na_by_class = Counter(e.get("hostClass") for e in (payload.get("endpoints") or ())
                          if e.get("coverage") == "na")

    if cov is None:
        integrations = _node("integrations", None,
                             note="not counted — this scan predates the coverage lifecycle")
        assets = _node("assets", counts.get("excluded"))
    else:
        vendors = counts.get("apis")
        tracked_note = (f"{cov.get('tracked', 0)} classified rows → {vendors} distinct vendors"
                        if vendors is not None else "")
        life = [_node("tracked", cov.get("tracked", 0), note=tracked_note),
                _node("queued", cov.get("queued", 0))]
        # needs-human / blocked are part of the partition and render even at 0: they are real
        # states a scan can be in, and hiding them would make a stuck repo look like a clean one.
        for k in ("needs-human", "blocked"):
            life.append(_node(k, cov.get(k, 0)))
        integrations = _node("integrations", counts.get("integrations"), children=life)
        # Every OBSERVED class becomes a child — the tuple only decides the order. Known
        # classes first (in _ASSET_CLASSES order), then any unmapped ones alphabetically, so
        # a new hostClass added to the classifier is never dropped and ordering stays stable.
        known = [c for c in _ASSET_CLASSES if c in na_by_class]
        unknown = sorted(c for c in na_by_class if c not in _ASSET_CLASSES)
        kids = [_node(c, na_by_class[c]) for c in known + unknown]
        assets = _node("assets", cov.get("na", counts.get("excluded")), children=kids)

    return [_node("detected", counts.get("detected"), children=[integrations, assets])]

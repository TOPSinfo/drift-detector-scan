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

import html as _html
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


def _sanitize(s) -> str:
    """Neutralise sequences a label/note could use to escape its own line inside the fenced
    block: CR/LF (a bare newline could inject a new Markdown line, including a heading) and
    backtick runs (three or more would close the fence early and let whatever follows render
    as live Markdown). A rendering concern only — this never rejects a payload, it just makes
    sure `md_tree`'s output can't stop being the plain text it claims to be. The tree's own
    `_LABELS` values and node keys are all closed-vocabulary today, so this is a no-op on every
    real call; it exists for the labels that are not guaranteed closed one layer up."""
    s = str(s)
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return s.replace("`", "'")


def _fmt(node) -> str:
    label = _sanitize(node["label"])
    if node["n"] is None:
        # A null count with no label would render as a bare, unidentifiable "not counted" —
        # the whole point of a null count is to say WHAT is not counted.
        return f"not counted ({label})" if label else "not counted"
    return f"{node['n']} {label}"


def _line(node, prefix, is_last, out):
    branch = "└─ " if is_last else "├─ "
    note = f"   ({_sanitize(node['note'])})" if node["note"] else ""
    out.append(f"{prefix}{branch}{_fmt(node)}{note}")
    kids = node["children"]
    for i, k in enumerate(kids):
        _line(k, prefix + ("   " if is_last else "│  "), i == len(kids) - 1, out)


def md_tree(nodes: list) -> list:
    """The tree as plain text, for drift.md and any terminal. Box-drawing characters, because
    the shape IS the explanation — a flat list of the same numbers is what failed to communicate."""
    out: list = []
    for root in nodes:
        out.append(_fmt(root))
        kids = root["children"]
        for i, k in enumerate(kids):
            _line(k, "", i == len(kids) - 1, out)
    return out


def _li(node) -> str:
    n = "null" if node["n"] is None else str(node["n"])
    # `_fmt` is the SAME wording md_tree uses ("73 detected" / "not counted (integrations)"),
    # so the two projections never drift apart on how they phrase a null count. `_fmt` already
    # runs the label through `_sanitize` (a fence-breaking concern); `html.escape` on top of
    # that is the HTML-specific concern (<, >, &, ") — a different hazard, both needed here.
    text = _html.escape(_fmt(node))
    note = (f' <span class="tnote">{_html.escape(_sanitize(node["note"]))}</span>'
            if node["note"] else "")
    kids = f"<ul>{''.join(_li(k) for k in node['children'])}</ul>" if node["children"] else ""
    return (f'<li data-node="{_html.escape(node["key"])}" data-n="{n}" '
            f'data-unit="{_html.escape(node["unit"])}">'
            f'<span class="tc">{text}</span>{note}{kids}</li>')


def html_tree(nodes: list) -> str:
    """The tree as structured markup — a <ul>, never a <pre>.

    The attributes are the contract: `verify` parses `data-n` and asserts children sum to their
    parent, and that each `data-node` matches drift.json. A <pre> could only be grepped, which is
    how a wrong number would survive on a page nobody involved can see rendered. Plain markup,
    no framework bindings: it must be readable with JavaScript off.
    """
    return f'<ul class="tree">{"".join(_li(n) for n in nodes)}</ul>'

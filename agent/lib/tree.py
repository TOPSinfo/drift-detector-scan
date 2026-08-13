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

# The schema does not require `hostClass` on an endpoint — a real row can carry `null` or
# omit the field. Left as a bare None, that value becomes a node KEY (`_node(c, ...)` below,
# fed straight into `_li`'s `html.escape(node["key"])`), and `html.escape(None)` raises
# AttributeError — a whole render crashing over one under-classified row. Folding it into
# this sentinel BEFORE it ever reaches a node key means every downstream consumer (sorting,
# escaping, the verify node-set check) only ever sees a plain string, and the row is still
# counted honestly rather than silently dropped to make the crash go away.
_NULL_HOST_CLASS = "(no hostClass)"

# Same problem, one level down: `domain` is nullable too (schema: ["string", "null"]), and a
# row's host becomes both its visible text and its `data-row` attribute. A bare None there
# would hit the same crash `_NULL_HOST_CLASS` exists to avoid, one layer later.
_NULL_DOMAIN = "(unknown host)"

# Task 5d: an endpoint's `repo` field is likewise optional (older payloads, or a caller that
# never set it). Endpoints missing it are grouped under this one sentinel bucket rather than
# dropped, so a payload with SOME repo-tagged rows and some without still sums honestly — and
# a payload where EVERY row lacks it collapses to exactly one group, which is what keeps the
# repo level from appearing (see `build`'s `multi_repo` gate: it fires on >1 distinct group).
_NULL_REPO = "(unknown repo)"

_LABELS = {
    "detected": "detected", "integrations": "integrations", "assets": "assets",
    "tracked": "tracked", "queued": "queued", "needs-human": "needs human", "blocked": "blocked",
}


def _node(key, n, *, note="", children=None, unit="rows", rows=None, has_rows=False,
          label=None, repo=None):
    return {"key": key, "label": label if label is not None else _LABELS.get(key, key), "n": n,
            "unit": unit, "note": note, "children": children or [], "rows": rows or [],
            # `has_rows` is a distinct flag from `bool(rows)`: a bucket that is a legitimate
            # row-bearing leaf (tracked/queued/needs-human/blocked, or an asset hostClass) but
            # happens to have zero matching endpoints must still assert "0 rows rendered" — an
            # empty `rows` list alone can't tell a real zero apart from "this node never carries
            # rows at all" (detected/integrations/assets, which are sums, not row buckets).
            "has_rows": has_rows,
            # Task 5d: `repo` is set ONLY on a repo-level node (its raw repo string — the
            # segment `data-repo` carries and `data-path` uses, since the repo's actual NAME,
            # not the shared semantic key "repo", is what disambiguates one repo's `tracked`
            # from another's). `path` is filled in by `_assign_paths` once the whole tree
            # exists — every node needs its full ancestor chain first, which recursive
            # construction here (children built before their parent) does not have yet.
            "repo": repo, "path": None}


def _assign_paths(nodes, prefix=None):
    """The node's full, UNIQUE path — e.g. `detected/acmegrocer-foods/integrations/tracked` — the
    identity `verify`'s checks key on now that `data-node` (tracked/queued/boilerplate/repo)
    repeats once per repo. A repo node's own path segment is its REPO NAME, not the shared key
    "repo"; every other node's segment is its own key, exactly the chain today's single-repo
    tree already implies (detected/integrations/tracked, unchanged)."""
    for n in nodes:
        seg = n["repo"] if n.get("repo") else n["key"]
        n["path"] = seg if prefix is None else f"{prefix}/{seg}"
        _assign_paths(n["children"], n["path"])


def _row(e: dict, catalog_by_vendor: dict, bucket: str) -> dict:
    """One row for a single endpoint record: the host, its call-site count, and — only for the
    buckets where it is load-bearing — the catalog join (`tracked`) or the own-infra heuristic's
    reasoning (`queued`). `files[]` can be TRUNCATED relative to `file_count` (measured on the
    reference repo: 16 of 73 endpoints carry fewer locations than their file_count), so this
    records both numbers rather than just the list — rendering the short list unqualified would
    claim completeness while silently hiding the rest.
    """
    files = list(e.get("files") or [])
    file_count = e.get("file_count")
    shown = len(files)
    row = {"host": e.get("domain") or _NULL_DOMAIN, "count": file_count, "locs": files,
          "shown": shown, "total": file_count if file_count is not None else shown,
          "truncated": file_count is not None and file_count > shown,
          "vendor": None, "version": None, "verdict": None, "reason": None}
    if bucket == "tracked":
        vendor = e.get("vendor")
        row["vendor"], row["version"] = vendor, e.get("version")
        # Absent from payload["catalog"] reads the same as an explicit UNAUDITED verdict would
        # — no attestation on file for this vendor either way — and UNAUDITED is the honesty
        # signal this row exists to surface, so it is the fallback, not a blank.
        row["verdict"] = catalog_by_vendor.get(vendor, "UNAUDITED") if vendor else "UNAUDITED"
    elif bucket == "queued":
        row["reason"] = e.get("ownInfraReason")
    return row


def _lifecycle_and_assets_from_endpoints(endpoints, catalog_by_vendor):
    """The `integrations`/`assets` subtree derived ENTIRELY from a list of endpoint rows, no
    `counts` involved. Used for a repo's own subtree in a multi-repo tree: `payload["counts"]`
    is a whole-scan aggregate with no per-repo split, so a repo's lifecycle/asset numbers can
    only come from its own rows — mirroring the same partition the single-repo branch of
    `build` computes from `counts.coverage`/`na_by_class`, just sourced locally instead of
    from the payload's aggregate tally.
    """
    by_coverage: dict = {"tracked": [], "queued": [], "needs-human": [], "blocked": []}
    na_rows_by_class: dict = {}
    for e in endpoints:
        c = e.get("coverage")
        if c in by_coverage:
            by_coverage[c].append(e)
        elif c == "na":
            na_rows_by_class.setdefault(e.get("hostClass") or _NULL_HOST_CLASS, []).append(e)
    na_by_class = Counter({k: len(v) for k, v in na_rows_by_class.items()})

    tracked_eps = by_coverage["tracked"]
    vendors = len({e.get("vendor") for e in tracked_eps if e.get("vendor")})
    tracked_note = (f"{len(tracked_eps)} classified rows → {vendors} distinct vendors"
                    if tracked_eps else "")
    life = [_node("tracked", len(tracked_eps), note=tracked_note, has_rows=True,
                  rows=[_row(e, catalog_by_vendor, "tracked") for e in tracked_eps]),
            _node("queued", len(by_coverage["queued"]), has_rows=True,
                  rows=[_row(e, catalog_by_vendor, "queued") for e in by_coverage["queued"]])]
    # needs-human / blocked are part of the partition and render even at 0: they are real
    # states a scan can be in, and hiding them would make a stuck repo look like a clean one.
    for k in ("needs-human", "blocked"):
        life.append(_node(k, len(by_coverage[k]), has_rows=True,
                          rows=[_row(e, catalog_by_vendor, k) for e in by_coverage[k]]))
    # `integrations.n` is defined as the SUM of its own children (never independently
    # recounted from `len(endpoints)`) — so a repo's subtree always sums to itself even if an
    # endpoint somehow carries a `coverage` value outside the five recognised states.
    integrations = _node("integrations", sum(len(v) for v in by_coverage.values()), children=life)
    # Every OBSERVED class becomes a child — the tuple only decides the order. Known
    # classes first (in _ASSET_CLASSES order), then any unmapped ones alphabetically, so
    # a new hostClass added to the classifier is never dropped and ordering stays stable.
    known = [c for c in _ASSET_CLASSES if c in na_by_class]
    unknown = sorted(c for c in na_by_class if c not in _ASSET_CLASSES)
    kids = [_node(c, na_by_class[c], has_rows=True,
                  rows=[_row(e, catalog_by_vendor, c) for e in na_rows_by_class[c]])
            for c in known + unknown]
    assets = _node("assets", sum(na_by_class.values()), children=kids)
    return integrations, assets


def build(payload: dict) -> list:
    """The node tree for `payload`. One root (`detected`); children sum to their parent.

    A count that cannot be derived is None with a `note` saying why — never 0, because a
    confident zero over missing data is the exact failure this tool exists to refuse.

    Task 5d: when the payload's endpoints span MORE THAN ONE repo, a repo level is inserted
    between the root and the lifecycle/asset split — each repo carrying its own complete
    breakdown, in a fixed alphabetical order (never by count, so two runs of the same payload
    render identically and the biggest repo never jumps to the front). A single-repo payload
    (today's overwhelming case, and every scan before this one) takes the ORIGINAL code path
    below unchanged — there is nothing to disambiguate, so nothing new renders.
    """
    counts = payload.get("counts") or {}
    cov = counts.get("coverage")
    catalog_by_vendor = {c.get("vendor"): c.get("verdict")
                         for c in (payload.get("catalog") or []) if c.get("vendor")}
    # `have_endpoints` distinguishes "the payload never carried per-endpoint detail" (a legacy
    # shape, or a caller that only ever populated counts) from "it did, and there are zero" — the
    # same distinction `test_assets_render_childless_rather_than_wrong_without_endpoints` already
    # draws for the asset breakdown. Without it, a lifecycle leaf whose `n` comes from
    # `counts.coverage` (never from the endpoint list) would claim rows it has no data to back,
    # which is exactly the "cannot see" rendered as "clean" failure this tool exists to refuse —
    # so absent endpoints means no row claim at all, not a row claim of zero.
    have_endpoints = payload.get("endpoints") is not None
    endpoints = payload.get("endpoints") or ()

    # Task 5d: group by repo BEFORE anything else. A row missing `repo` entirely falls into
    # `_NULL_REPO`'s own group rather than being silently dropped from every sum below it —
    # see that sentinel's own comment. `multi_repo` fires on more than one DISTINCT group,
    # which also correctly covers "every row is missing `repo`" (exactly one group, the
    # sentinel) as the single-repo case it actually is.
    repo_groups: dict = {}
    for e in endpoints:
        repo_groups.setdefault(e.get("repo") or _NULL_REPO, []).append(e)
    if len(repo_groups) > 1:
        repo_children = []
        for repo_name in sorted(repo_groups):        # fixed alphabetical order, never by count
            integrations, assets = _lifecycle_and_assets_from_endpoints(
                repo_groups[repo_name], catalog_by_vendor)
            repo_children.append(_node("repo", integrations["n"] + assets["n"],
                                       label=repo_name, repo=repo_name,
                                       children=[integrations, assets]))
        roots = [_node("detected", counts.get("detected"), children=repo_children)]
        _assign_paths(roots)
        return roots

    # One pass over the endpoints: bucket by coverage state (the lifecycle leaves' rows) and,
    # for `na` rows, by hostClass (the asset breakdown's rows) — the SAME source
    # `na_by_class`'s count already came from, now keeping the records themselves too.
    by_coverage: dict = {"tracked": [], "queued": [], "needs-human": [], "blocked": []}
    na_rows_by_class: dict = {}
    for e in endpoints:
        c = e.get("coverage")
        if c in by_coverage:
            by_coverage[c].append(e)
        elif c == "na":
            na_rows_by_class.setdefault(e.get("hostClass") or _NULL_HOST_CLASS, []).append(e)
    # The asset breakdown comes from the ENDPOINT ROWS, never from counts.hostClasses.
    # hostClasses tallies all 73 endpoints, so its asset-class entries sum to 45 against an
    # assets total of 43: a token-claimed `own-infra` row is kept QUEUED (it might be a real
    # third party), which makes it an integration, not an asset. Deriving from hostClasses
    # would put the tree out by exactly that difference — the arithmetic failure this tree
    # exists to make impossible.
    na_by_class = Counter({k: len(v) for k, v in na_rows_by_class.items()})

    if cov is None:
        integrations = _node("integrations", None,
                             note="not counted — this scan predates the coverage lifecycle")
        assets = _node("assets", counts.get("excluded"))
    else:
        vendors = counts.get("apis")
        tracked_note = (f"{cov.get('tracked', 0)} classified rows → {vendors} distinct vendors"
                        if vendors is not None else "")
        life = [_node("tracked", cov.get("tracked", 0), note=tracked_note, has_rows=have_endpoints,
                      rows=[_row(e, catalog_by_vendor, "tracked") for e in by_coverage["tracked"]]),
                _node("queued", cov.get("queued", 0), has_rows=have_endpoints,
                      rows=[_row(e, catalog_by_vendor, "queued") for e in by_coverage["queued"]])]
        # needs-human / blocked are part of the partition and render even at 0: they are real
        # states a scan can be in, and hiding them would make a stuck repo look like a clean one.
        for k in ("needs-human", "blocked"):
            life.append(_node(k, cov.get(k, 0), has_rows=have_endpoints,
                              rows=[_row(e, catalog_by_vendor, k) for e in by_coverage[k]]))
        integrations = _node("integrations", counts.get("integrations"), children=life)
        # Every OBSERVED class becomes a child — the tuple only decides the order. Known
        # classes first (in _ASSET_CLASSES order), then any unmapped ones alphabetically, so
        # a new hostClass added to the classifier is never dropped and ordering stays stable.
        known = [c for c in _ASSET_CLASSES if c in na_by_class]
        unknown = sorted(c for c in na_by_class if c not in _ASSET_CLASSES)
        kids = [_node(c, na_by_class[c], has_rows=True,
                      rows=[_row(e, catalog_by_vendor, c) for e in na_rows_by_class[c]])
                for c in known + unknown]
        assets = _node("assets", cov.get("na", counts.get("excluded")), children=kids)

    roots = [_node("detected", counts.get("detected"), children=[integrations, assets])]
    _assign_paths(roots)
    return roots


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


def _root_line(root) -> str:
    """The root's own line, in BOTH renderers' shared wording: `_fmt` plus its note, formatted
    the same way `_line` folds a note onto every non-root line. `_li` renders a node's note
    unconditionally regardless of depth; `md_tree` must too, or the two projections disagree on
    the one node `check_tree_parity` anchors on."""
    note = f"   ({_sanitize(root['note'])})" if root["note"] else ""
    return f"{_fmt(root)}{note}"


def md_tree(nodes: list) -> list:
    """The tree as plain text, for drift.md and any terminal. Box-drawing characters, because
    the shape IS the explanation — a flat list of the same numbers is what failed to communicate."""
    out: list = []
    for root in nodes:
        out.append(_root_line(root))
        kids = root["children"]
        for i, k in enumerate(kids):
            _line(k, "", i == len(kids) - 1, out)
    return out


def _row_html(r: dict) -> str:
    """One host's row: its call-site count, and — only when load-bearing — the catalog join or
    the own-infra reasoning, plus (if it has any) a nested, native `<details>` of its own
    file:line locations. Never a `<li>`/`<ul>`: rows must stay outside the vocabulary
    `verify._tree_nodes`/`_parse_rendered_tree` walk, so a row can never be mistaken for a tree
    node (see `check_tree_rows`'s docstring) — that boundary is what keeps tree-parity and
    tree-node-set unaffected by rows existing at all.
    """
    host = _html.escape(str(r["host"]))
    count = "—" if r["count"] is None else str(r["count"])
    extra = ""
    if r["verdict"] is not None:
        vendor = _html.escape(str(r["vendor"])) if r["vendor"] else "(vendor unknown)"
        version = f" {_html.escape(str(r['version']))}" if r.get("version") else ""
        verdict = _html.escape(str(r["verdict"]))
        extra = (f' <span class="rvendor">{vendor}{version}</span>'
                f' <span class="verdict">{verdict}</span>')
    elif r["reason"]:
        extra = f' <span class="rreason">{_html.escape(str(r["reason"]))}</span>'
    locs_html = ""
    if r["locs"]:
        items = "".join(f'<div data-loc="{_html.escape(loc)}">{_html.escape(loc)}</div>'
                        for loc in r["locs"])
        # Requirement 5: files[] can be a TRUNCATED sample of file_count. Showing the short
        # list with no caveat would read as "here is where it is called" while silently
        # hiding the rest — exactly the "cannot see" rendered as "clean" this tool refuses.
        trunc = (f'<div class="rtrunc">showing {r["shown"]} of {r["total"]}</div>'
                 if r["truncated"] else "")
        locs_html = (f'<details class="locs"><summary>{r["shown"]} location(s)</summary>'
                    f'{items}{trunc}</details>')
    return (f'<div class="row" data-row="{host}">'
            f'<span class="rhost">{host}</span> <span class="rcount">{count}</span>'
            f'{extra}{locs_html}</div>')


def _rows_html(rows: list) -> str:
    """A node's own hosts, native-collapsible. Emits nothing for zero rows — a claimed-but-empty
    bucket has no hosts to expand to, so there is nothing to disclose beyond the count already on
    the node's own line."""
    if not rows:
        return ""
    return (f'<details class="rows"><summary>{len(rows)} host(s)</summary>'
            f'{"".join(_row_html(r) for r in rows)}</details>')


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
    # Rows are appended AFTER kids, never inserted between the opening `<li ...>` tag and the
    # `<span class="tc">`/`<span class="tnote">` pair immediately following it —
    # `verify._TREE_LI_TEXT` anchors on that exact adjacency (tree-parity/tree-text-mismatch),
    # and it does not require the `<li>` to end there, so appending after is invisible to it.
    rows_html = _rows_html(node["rows"]) if node["has_rows"] else ""
    # Task 5d: `data-path` is the node's UNIQUE identity (verify keys on this now that
    # `data-node` repeats once per repo); it sits right after `data-node`, which several
    # existing invariants/tests locate via `<li data-node="X"[^>]*>` — a fixed prefix that
    # must keep matching, so nothing may be inserted BEFORE `data-node`. `data-repo` is
    # appended LAST, right before `>`, and only for a repo node, so it never disturbs
    # `verify._TREE_LI_TEXT`'s fixed `data-node/data-path/data-n/data-unit` prefix either.
    path = node.get("path") or node["key"]
    repo_attr = f' data-repo="{_html.escape(str(node["repo"]))}"' if node.get("repo") else ""
    return (f'<li data-node="{_html.escape(node["key"])}" data-path="{_html.escape(path)}" '
            f'data-n="{n}" data-unit="{_html.escape(node["unit"])}"{repo_attr}>'
            f'<span class="tc">{text}</span>{note}{kids}{rows_html}</li>')


def html_tree(nodes: list) -> str:
    """The tree as structured markup — a <ul>, never a <pre>.

    The attributes are the contract: `verify` parses `data-n` and asserts children sum to their
    parent, and that each `data-node` matches drift.json. A <pre> could only be grepped, which is
    how a wrong number would survive on a page nobody involved can see rendered. Plain markup,
    no framework bindings: it must be readable with JavaScript off.
    """
    return f'<ul class="tree">{"".join(_li(n) for n in nodes)}</ul>'


# Every node key `build()` can produce needs an entry here — `verify.check_tree_definitions`
# enforces that the pairing between the rendered tree and this glossary can never silently drift
# apart, and `tests/test_tree_definitions.py::test_every_node_has_a_definition` enforces that the
# CONTENT is actually complete (see `html_definitions` below for why the runtime check can't be
# the one to enforce completeness). Written for someone who has been away a week and can no
# longer remember what `queued` or `unaudited` mean.
DEFINITIONS = {
    "detected": "Every outbound endpoint the scan read. The complete inventory — everything "
               "below is a filter over this, never a gate that hides a row.",
    # Task 5d: only appears when the scan covered more than one repo. `data-node="repo"` is
    # the same for every repo — the repo's own NAME lives in its label and `data-repo`, not
    # here — so this one entry covers however many repos a fleet scan carries.
    "repo": "One repository the scan covered. Appears only when a scan spans more than one — "
           "the numbers below are that repo's own, never mixed with another's.",
    "integrations": "Third-party services this code actually calls.",
    "tracked": "The vendor is recognised and its retirements are monitored. Counted in endpoint "
              "rows; the distinct-vendor figure is the annotation beside it.",
    "queued": "A real integration the scan detected but cannot yet name. It is IN the audit "
             "backlog — this is work outstanding, not a clean result.",
    "needs-human": "Research ran and could not reach a confident verdict.",
    "blocked": "Research could not fetch the vendor's page at all.",
    "assets": "Not third-party services: bundled libraries, CDNs, spec and documentation links, "
             "social embeds, and this repo's own infrastructure.",
    "boilerplate": "Schema, namespace and documentation hosts — links, never a runtime call.",
    "social-widget": "Share, embed and follow destinations.",
    "vendored-lib": "Front-end libraries the app bundles or links its own copy of.",
    "asset-cdn": "Fonts, icons, images and generic static-asset CDNs.",
    "own-infra": "This project's own hosts, derived from the repo's name and git remote.",
    "analytics": "Trackers and tag managers with no first-class API to audit.",
    # Not reachable via _endpoints_of today (a null hostClass is coerced to "api"/"unclassified"
    # before it ever reaches a payload endpoint — see dashboard_render._endpoints_of), but
    # `_NULL_HOST_CLASS` above exists precisely because the schema does not forbid it, so this
    # stays defined defensively rather than leaving a reachable-in-principle key undocumented.
    _NULL_HOST_CLASS: "An endpoint recorded with no hostClass at all.",
}


def html_definitions(nodes: list) -> str:
    """A <details> glossary keyed to the tree's rendered nodes. Not tooltips: those are neither
    discoverable nor checkable from source, and this page cannot be checked any other way.

    Emits a `data-def` for every KEY the tree actually renders, even one `DEFINITIONS` has no
    prose for (`.get(k, "")` — an empty <dd>, never a missing <dt>). That is deliberate: a future
    hostClass a classifier emits before anyone has written its glossary entry must not turn a
    real repo's `verify` red (see `verify.check_tree_definitions`, which only asserts this
    pairing, not that the text is non-empty). Completeness of the prose itself is a dev-time
    concern, covered by a plain pytest test over `DEFINITIONS`, not a runtime gate over
    someone else's scan.
    """
    keys: list = []

    def walk(ns):
        for n in ns:
            if n["key"] not in keys:
                keys.append(n["key"])
            walk(n["children"])
    walk(nodes)
    items = "".join(
        f'<dt data-def="{_html.escape(k)}">{_html.escape(k)}</dt>'
        f'<dd>{_html.escape(DEFINITIONS.get(k, ""))}</dd>' for k in keys)
    return ('<details class="defs"><summary>What these mean</summary>'
            f'<dl>{items}</dl></details>')

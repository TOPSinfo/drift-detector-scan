# Dashboard Reframe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the cockpit explain itself — one server-rendered, machine-checked tree replacing a tile strip that doesn't sum, two sections instead of three planes, AI folded in as provenance, and research that runs itself.

**Architecture:** One pure builder (`agent/lib/tree.py`) turns `drift.json` into a node structure; two thin renderers emit it as ASCII into `drift.md` and as a nested `<ul>` into `dashboard.html`. Because both come from one function over one payload they cannot disagree, and `verify` checks each against the payload rather than against each other — making the tree a *verified projection*, not a template. Then the AI plane collapses into Vendor Drift as badges and inline status, and research stops asking permission.

**Tech Stack:** Python 3.11+ (stdlib + PyYAML only), pytest, vanilla Vue 3 + plain HTML in `agent/assets/` (no build step), YAML catalogs.

## Global Constraints

- **Runtime dependencies are stdlib + PyYAML only.** `jsonschema` is test-only.
- **Deterministic.** Same inputs → byte-identical output. No wall-clock in logic; `now` is passed in.
- **"Cannot see" ≠ "clean", and absent ≠ zero.** A node whose count is unknowable renders `data-n="null"` and a reason, never `0`. "Research never ran" must stay distinguishable from "research found nothing".
- **The AI firewall holds.** `leads-data` / `adhoc-data` / `research-data` stay separate blobs; `verify.check_ai_firewall` keeps asserting no AI record reaches the certified payload. Tree and header numbers derive from `drift-data` **only**.
- **The tree must render with JavaScript entirely disabled.** Plain anchors, no reactive state. If it needs JS to be correct, it is not a projection.
- **Every guard proven against its bug** — shown to FAIL before the fix lands. Not optional.
- **Nobody on this project can see rendered HTML.** Claims about appearance are not evidence; this blind spot has shipped bugs twice. Assert on emitted source and payload parity.
- **Test command:** `.venv/bin/python -m pytest -q` from the repo root. Baseline at plan time: **989 passed, 3 skipped**.
- Three existing invariants are substring checks over template/JS source and WILL trip when bindings move — that is them working: `check_timeline_lanes` (needs `timeline.dated` + `timeline.undated`), `check_accessor_coverage` (constrains loop-var names `a`/`e`/`p`/`cv`/`row`), and `check_blob_matches_payload` (id-anchored, so new blobs are safe but the certified one must stay byte-identical).

---

## Stage 1 — the tree (certified data only, zero firewall exposure)

### Task 1: `agent/lib/tree.py` — the node builder

**Files:**
- Create: `agent/lib/tree.py`
- Test: `tests/test_tree.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tree.build(payload: dict) -> list` returning a list of node dicts, each
  `{"key": str, "label": str, "n": int | None, "unit": str, "note": str, "children": list}`.
  Tasks 2, 3 and 4 all consume this.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tree.py`:

```python
"""The tree is a PROJECTION of drift.json, not a widget. Its arithmetic is the thing being
guaranteed, so it is computed once, in Python, and rendered twice — never computed in a browser
nobody on this project can observe."""
from agent.lib import tree


def _eps():
    """Endpoint rows mirroring a real scan. The asset breakdown MUST be derived from these,
    not from counts.hostClasses — see test_assets_break_down_by_hostclass for why."""
    def rows(n, hc, cov):
        return [{"domain": f"h{i}.{hc}.test", "hostClass": hc, "coverage": cov} for i in range(n)]
    return (rows(27, "api", "tracked")
            + rows(2, "own-infra", "queued") + rows(1, "unclassified", "queued")
            + rows(20, "boilerplate", "na") + rows(12, "social-widget", "na")
            + rows(5, "vendored-lib", "na") + rows(3, "asset-cdn", "na")
            + rows(3, "own-infra", "na"))


def _payload():
    # mirrors a real scan: 73 detected = 30 integrations + 43 assets; 30 = 27 tracked + 3 queued
    return {"counts": {
        "detected": 73, "integrations": 30, "excluded": 43, "unknown": 3, "apis": 21,
        "coverage": {"tracked": 27, "queued": 3, "needs-human": 0, "blocked": 0, "na": 43},
        "hostClasses": {"api": 27, "boilerplate": 20, "social-widget": 12, "vendored-lib": 5,
                        "asset-cdn": 3, "own-infra": 5, "unclassified": 1},
    }, "endpoints": _eps()}


def _flat(nodes, out=None):
    out = {} if out is None else out
    for n in nodes:
        out[n["key"]] = n
        _flat(n["children"], out)
    return out


def test_root_is_detected_and_children_sum_to_it():
    nodes = tree.build(_payload())
    assert len(nodes) == 1 and nodes[0]["key"] == "detected"
    root = nodes[0]
    assert root["n"] == 73
    assert sum(c["n"] for c in root["children"]) == 73


def test_integrations_splits_into_the_coverage_lifecycle():
    f = _flat(tree.build(_payload()))
    assert f["integrations"]["n"] == 30
    assert sum(c["n"] for c in f["integrations"]["children"]) == 30
    assert f["tracked"]["n"] == 27 and f["queued"]["n"] == 3


def test_every_node_declares_a_unit():
    """The bug this replaces: `Tracked` counted distinct VENDORS while its neighbours counted
    endpoint ROWS, so the tile strip summed to 67 against a Detected of 73, with nothing on
    screen saying so. Every node now counts rows and says which unit it is in."""
    for n in _flat(tree.build(_payload())).values():
        assert n["unit"], n["key"]
        assert n["unit"] == "rows"


def test_the_vendor_count_survives_as_an_annotation_not_a_node():
    """21 distinct vendors is real and useful — but it is a different unit, so it may never be
    a sibling of a row count. It rides on `tracked` as a note."""
    f = _flat(tree.build(_payload()))
    assert "21" in f["tracked"]["note"] and "vendor" in f["tracked"]["note"].lower()
    assert f["tracked"]["n"] == 27          # the NODE stays in rows


def test_assets_break_down_by_hostclass():
    """The children MUST come from the endpoint rows, not from `counts.hostClasses`.

    hostClasses is a tally over ALL 73 endpoints, so its asset-class entries sum to 45 while the
    assets total is 43: the 2 token-claimed `own-infra` rows are kept QUEUED (they might be a real
    third party), which makes them integrations, not assets. Deriving from hostClasses would break
    the tree's arithmetic by exactly that 2 — the bug this whole tree exists to make impossible.
    """
    f = _flat(tree.build(_payload()))
    assert f["assets"]["n"] == 43
    kids = {c["key"]: c["n"] for c in f["assets"]["children"]}
    assert kids["boilerplate"] == 20 and kids["social-widget"] == 12
    assert kids["own-infra"] == 3          # 3, not the 5 that hostClasses reports
    assert sum(kids.values()) == 43


def test_assets_render_childless_rather_than_wrong_without_endpoints():
    """No endpoints to derive from means no breakdown — never a guessed one."""
    p = _payload(); del p["endpoints"]
    f = _flat(tree.build(p))
    assert f["assets"]["n"] == 43 and f["assets"]["children"] == []


def test_an_unknowable_count_is_null_with_a_reason_never_zero():
    """Absent is not zero. A payload missing `coverage` cannot render a confident 0."""
    p = _payload()
    del p["counts"]["coverage"]
    f = _flat(tree.build(p))
    assert f["integrations"]["n"] is None
    assert f["integrations"]["note"]


def test_build_is_pure_and_deterministic():
    p = _payload()
    assert tree.build(p) == tree.build(p)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_tree.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.lib.tree'`.

- [ ] **Step 3: Write the builder**

Create `agent/lib/tree.py`:

```python
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

# Assets are grouped by hostClass. Ordered loudest-first so the biggest bucket leads, and
# fixed (not sorted by count) so two runs of the same payload render identically.
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
        kids = [_node(c, na_by_class[c]) for c in _ASSET_CLASSES if na_by_class.get(c)]
        assets = _node("assets", cov.get("na", counts.get("excluded")), children=kids)

    return [_node("detected", counts.get("detected"), children=[integrations, assets])]
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_tree.py -q`
Expected: PASS (7 tests).

Then confirm the sums hold on REAL data, not just the fixture:

```bash
cd /tmp && .venv/bin/python -c "
import json,sys; sys.path.insert(0,'/home/tops/Projects/tops/drift/drift-detector-scan')
from agent.lib import tree
p=json.load(open('/home/tops/Projects/sandbox/promoteplus-crm/.drift-detector/drift.json'))
r=tree.build(p)[0]
print(r['n'], '==', sum(c['n'] for c in r['children']))
"
```
Expected: `73 == 73`. If it does not balance, the builder is wrong — fix it, do not adjust the test.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/tree.py tests/test_tree.py
git commit -m "feat(tree): compute the coverage breakdown once, in Python"
```

---

### Task 2: the ASCII tree lands in `drift.md`

**Files:**
- Modify: `agent/lib/tree.py` (add `md_tree`)
- Modify: `agent/lib/md_render.py` (call it in `render_markdown`, after the Summary table)
- Test: `tests/test_tree.py`, `tests/test_md_render.py`

**Interfaces:**
- Consumes: `tree.build` from Task 1.
- Produces: `tree.md_tree(nodes: list) -> list[str]` — the ASCII lines, no trailing newline.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tree.py`:

```python
def test_md_tree_renders_the_shape_the_owner_could_read():
    """This exact shape is why the tree exists — it was legible in a chat message when the
    tile strip was not, so it becomes a real artifact in the file you can read without a browser."""
    lines = tree.md_tree(tree.build(_payload()))
    body = "\n".join(lines)
    assert "73 detected" in body
    assert "30 integrations" in body
    assert "27 tracked" in body and "3 queued" in body
    assert "43 assets" in body
    assert "21 distinct vendors" in body          # the annotation, not a node
    assert "boilerplate 20" in body
    # box-drawing, so it reads as a tree in a terminal and on GitHub
    assert "├─" in body and "└─" in body


def test_md_tree_states_a_null_count_rather_than_printing_zero():
    p = _payload()
    del p["counts"]["coverage"]
    body = "\n".join(tree.md_tree(tree.build(p)))
    assert "not counted" in body
    assert "0 integrations" not in body
```

Append to `tests/test_md_render.py`:

```python
def test_markdown_carries_the_coverage_tree():
    from agent.lib.md_render import render_markdown
    md = render_markdown(_payload_with_counts(), "2026-08-13")   # use this file's existing helper
    assert "## Coverage tree" in md
    assert "detected" in md and "├─" in md
```

- [ ] **Step 2: Run and watch both fail**

Run: `.venv/bin/python -m pytest tests/test_tree.py tests/test_md_render.py -q`
Expected: FAIL — `md_tree` does not exist; the markdown has no tree section.

If `tests/test_md_render.py` has no payload helper by that name, read the file and use whatever
fixture it already provides rather than inventing one.

- [ ] **Step 3: Add the ASCII renderer**

Append to `agent/lib/tree.py`:

```python
def _line(node, prefix, is_last, out):
    branch = "└─ " if is_last else "├─ "
    n = "not counted" if node["n"] is None else f"{node['n']} {node['label']}"
    note = f"   ({node['note']})" if node["note"] else ""
    out.append(f"{prefix}{branch}{n}{note}")
    kids = node["children"]
    for i, k in enumerate(kids):
        _line(k, prefix + ("   " if is_last else "│  "), i == len(kids) - 1, out)


def md_tree(nodes: list) -> list:
    """The tree as plain text, for drift.md and any terminal. Box-drawing characters, because
    the shape IS the explanation — a flat list of the same numbers is what failed to communicate."""
    out: list = []
    for root in nodes:
        head = "not counted" if root["n"] is None else f"{root['n']} {root['label']}"
        out.append(head)
        kids = root["children"]
        for i, k in enumerate(kids):
            _line(k, "", i == len(kids) - 1, out)
    return out
```

- [ ] **Step 4: Call it from `render_markdown`**

In `agent/lib/md_render.py`, add the import at the top with the others:

```python
from agent.lib import tree as _tree
```

Then in `render_markdown`, immediately AFTER the Summary table section and BEFORE the
`## Coverage — what the scan is sure of` section, insert:

```python
    # The coverage tree: the same numbers as the tables, in the shape that actually communicates.
    # Rendered from the payload here (not in the browser) so `verify` can check it against
    # drift.json — a projection, like every other surface this tool emits.
    L += ["## Coverage tree", ""]
    L += ["```"] + _tree.md_tree(_tree.build(payload)) + ["```", ""]
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_tree.py tests/test_md_render.py -q`
Expected: PASS. Then the full suite — `check_mermaid_wellformed` and `check_md_matches_payload`
both parse `drift.md` and a new fenced block could disturb them:
`.venv/bin/python -m pytest -q` → expected all pass. If `_parse_md_tables` now mis-reads the
fenced tree as a table, fix the PARSER to skip fenced blocks, not the tree.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/tree.py agent/lib/md_render.py tests/test_tree.py tests/test_md_render.py
git commit -m "feat(md): the coverage tree becomes a real artifact in drift.md"
```

---

### Task 3: the `<ul>` tree lands in `dashboard.html`

**Files:**
- Modify: `agent/lib/tree.py` (add `html_tree`)
- Modify: `agent/lib/dashboard_render.py` (inject it in `render_payload`)
- Modify: `agent/assets/dashboard.css` (tree styles)
- Test: `tests/test_tree.py`, `tests/test_dashboard_tree.py`

**Interfaces:**
- Consumes: `tree.build` from Task 1.
- Produces: `tree.html_tree(nodes: list) -> str` — a `<ul class="tree">` fragment carrying
  `data-node`, `data-n` and `data-unit` on every `<li>`. Task 4 parses exactly these attributes.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard_tree.py`:

```python
import re
from agent.lib import tree
from agent.lib.dashboard_render import render_payload


def _payload():
    return {"counts": {"detected": 73, "integrations": 30, "excluded": 43, "unknown": 3,
                       "apis": 21,
                       "coverage": {"tracked": 27, "queued": 3, "needs-human": 0,
                                    "blocked": 0, "na": 43},
                       "hostClasses": {"boilerplate": 20, "social-widget": 12,
                                       "vendored-lib": 5, "asset-cdn": 3, "own-infra": 5}},
            "generated": "2026-08-13", "endpoints": [], "catalog": [], "actions": [],
            "coverageGrades": [], "notes": []}


def test_tree_is_structured_markup_not_a_pre_block():
    """A <pre> can only be grepped; a <ul> with data attributes can be PARSED and its arithmetic
    checked. That difference is the whole reason this is server-rendered."""
    html = tree.html_tree(tree.build(_payload()))
    assert '<ul class="tree"' in html
    assert "<pre" not in html
    assert 'data-node="detected"' in html and 'data-n="73"' in html
    assert 'data-unit="rows"' in html


def test_every_li_carries_all_three_attributes():
    html = tree.html_tree(tree.build(_payload()))
    for li in re.findall(r"<li\b[^>]*>", html):
        assert "data-node=" in li and "data-n=" in li and "data-unit=" in li, li


def test_a_null_count_renders_null_and_a_reason_never_zero():
    p = _payload()
    del p["counts"]["coverage"]
    html = tree.html_tree(tree.build(p))
    assert 'data-n="null"' in html
    assert "not counted" in html


def test_the_tree_needs_no_javascript():
    """It must be readable with JS disabled — if it needs a framework to be correct, it is not
    a projection. No Vue bindings, no event handlers in the emitted fragment."""
    html = tree.html_tree(tree.build(_payload()))
    for banned in ("v-for", "v-if", "{{", "@click", "onclick"):
        assert banned not in html, banned


def test_the_tree_is_embedded_in_the_dashboard():
    html = render_payload(_payload(), "2026-08-13")
    assert '<ul class="tree"' in html
    assert 'data-node="detected"' in html


def test_html_is_escaped():
    p = _payload()
    p["counts"]["hostClasses"] = {"<script>x</script>": 4}
    html = tree.html_tree(tree.build(p))
    assert "<script>x</script>" not in html
```

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard_tree.py -q`
Expected: FAIL — `html_tree` does not exist.

- [ ] **Step 3: Add the HTML renderer**

Append to `agent/lib/tree.py`:

```python
import html as _html


def _li(node) -> str:
    n = "null" if node["n"] is None else str(node["n"])
    label = _html.escape(node["label"])
    count = "not counted" if node["n"] is None else str(node["n"])
    note = f' <span class="tnote">{_html.escape(node["note"])}</span>' if node["note"] else ""
    kids = f"<ul>{''.join(_li(k) for k in node['children'])}</ul>" if node["children"] else ""
    return (f'<li data-node="{_html.escape(node["key"])}" data-n="{n}" '
            f'data-unit="{_html.escape(node["unit"])}">'
            f'<span class="tn">{_html.escape(count)}</span> '
            f'<span class="tl">{label}</span>{note}{kids}</li>')


def html_tree(nodes: list) -> str:
    """The tree as structured markup — a <ul>, never a <pre>.

    The attributes are the contract: `verify` parses `data-n` and asserts children sum to their
    parent, and that each `data-node` matches drift.json. A <pre> could only be grepped, which is
    how a wrong number would survive on a page nobody involved can see rendered. Plain markup,
    no framework bindings: it must be readable with JavaScript off.
    """
    return f'<ul class="tree">{"".join(_li(n) for n in nodes)}</ul>'
```

- [ ] **Step 4: Inject it into the page**

In `agent/lib/dashboard_render.py`, import the module and insert the fragment into
`render_payload`'s list, immediately AFTER `TEMPLATE_SRC` and BEFORE the `drift-data` blob:

```python
from agent.lib import tree as _tree
```

```python
         TEMPLATE_SRC,
         # The coverage tree, rendered SERVER-SIDE from the same payload the blob carries. It is a
         # verified projection (see verify.check_tree_matches_payload), which a Vue-computed tree
         # could never be: its numbers would be produced in a browser nobody here can observe.
         '<section id="coverage-tree">' + _tree.html_tree(_tree.build(projection)) + '</section>',
```

Add minimal styles to `agent/assets/dashboard.css`:

```css
/* The coverage tree. Deliberately plain — the guarantee is the arithmetic, not the styling,
   and it must stay legible with CSS or JS disabled. */
#coverage-tree .tree, #coverage-tree .tree ul { list-style: none; margin: 0; padding-left: 1.25rem; }
#coverage-tree .tree > li { padding-left: 0; }
#coverage-tree .tn { font-variant-numeric: tabular-nums; font-weight: 600; }
#coverage-tree .tnote { opacity: .7; font-size: .9em; }
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard_tree.py -q` → PASS.
Then the full suite: `.venv/bin/python -m pytest -q`. `check_blob_matches_payload` is id-anchored
so a new section before the blob is safe — but confirm, and if it breaks, fix the injection point,
not the check.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/tree.py agent/lib/dashboard_render.py agent/assets/dashboard.css \
        tests/test_dashboard_tree.py
git commit -m "feat(dashboard): server-render the coverage tree as structured markup"
```

---

### Task 4: `verify` proves the tree

**Files:**
- Modify: `agent/lib/verify.py` (add `check_tree_matches_payload`, `check_tree_parity`)
- Modify: `agent/cli.py` (register both in the verify command's check list)
- Test: `tests/test_verify_tree.py`

**Interfaces:**
- Consumes: the emitted markup from Task 3 and the ASCII from Task 2.
- Produces: `verify.check_tree_matches_payload(html: str, payload: dict) -> None` and
  `verify.check_tree_parity(html: str, md_text: str) -> None`, both raising `Violation`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify_tree.py`:

```python
import pytest
from agent.lib import tree, verify


def _payload():
    return {"counts": {"detected": 73, "integrations": 30, "excluded": 43, "apis": 21,
                       "coverage": {"tracked": 27, "queued": 3, "needs-human": 0,
                                    "blocked": 0, "na": 43},
                       "hostClasses": {"boilerplate": 20, "social-widget": 12,
                                       "vendored-lib": 5, "asset-cdn": 3, "own-infra": 5}}}


def test_a_faithful_tree_passes():
    verify.check_tree_matches_payload(tree.html_tree(tree.build(_payload())), _payload())


def test_children_that_do_not_sum_to_their_parent_are_a_violation():
    """The bug class this replaces shipped for months: a tile strip whose numbers did not add up,
    on a page nobody involved can see rendered. Now the arithmetic is asserted at the layer that
    writes it."""
    html = tree.html_tree(tree.build(_payload())).replace('data-n="43"', 'data-n="44"', 1)
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(html, _payload())
    assert e.value.check == "tree-sums"


def test_a_node_disagreeing_with_the_payload_is_a_violation():
    """Internal consistency is not enough — a tree can be self-consistent and still be a fiction.
    This is what makes it a PROJECTION of drift.json rather than a decoration beside it."""
    html = tree.html_tree(tree.build(_payload()))
    html = html.replace('data-node="detected" data-n="73"', 'data-node="detected" data-n="99"')
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(html, _payload())
    assert e.value.check in ("tree-sums", "tree-payload")


def test_a_node_without_a_unit_is_a_violation():
    html = tree.html_tree(tree.build(_payload())).replace(' data-unit="rows"', "", 1)
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(html, _payload())
    assert e.value.check == "tree-units"


def test_ascii_and_html_trees_must_agree():
    """One builder, two renderers — so a divergence means a renderer is lying, not that the data
    changed."""
    p = _payload()
    good_md = "\n".join(tree.md_tree(tree.build(p)))
    verify.check_tree_parity(tree.html_tree(tree.build(p)), good_md)
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_parity(tree.html_tree(tree.build(p)), good_md.replace("73", "72"))
    assert e.value.check == "tree-parity"


def test_a_null_node_is_not_treated_as_zero():
    p = _payload(); del p["counts"]["coverage"]
    verify.check_tree_matches_payload(tree.html_tree(tree.build(p)), p)
```

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_verify_tree.py -q`
Expected: FAIL — `check_tree_matches_payload` does not exist.

- [ ] **Step 3: Implement the checks**

Add to `agent/lib/verify.py`, before `verify_payload`:

```python
_TREE_LI = re.compile(r'<li\b(?P<attrs>[^>]*)>')
_TREE_ATTR = re.compile(r'data-(?P<k>node|n|unit)="(?P<v>[^"]*)"')


def _tree_nodes(html: str) -> list:
    """[(key, n|None, unit)] in document order, from the emitted <li> attributes."""
    out = []
    for m in _TREE_LI.finditer(html):
        a = {mm.group("k"): mm.group("v") for mm in _TREE_ATTR.finditer(m.group("attrs"))}
        if "node" not in a:
            continue                      # an <li> outside the tree (the page has others)
        n = None if a.get("n") in (None, "null") else int(a["n"])
        out.append((a["node"], n, a.get("unit")))
    return out


def check_tree_matches_payload(html: str, payload: dict) -> None:
    """The coverage tree agrees with the payload it was rendered from, and adds up.

    The tile strip this replaces did NOT add up — `Tracked` counted distinct vendors while its
    neighbours counted endpoint rows, so it summed to 67 against a Detected of 73 with nothing on
    screen declaring the unit change. It survived because a rendered page cannot be checked by
    anything without eyes, and nobody on this project has them. Server-rendering the tree moves
    its numbers to a layer that CAN be checked, and this is the check.

    Three failures, each a real class:
      • tree-units   — a node with no declared unit (how the original bug hid);
      • tree-sums    — children that do not sum to their parent;
      • tree-payload — a node that disagrees with drift.json, i.e. self-consistent but false.
    """
    from agent.lib import tree as _tree
    nodes = _tree_nodes(html)
    if not nodes:
        raise Violation("tree-payload", "no coverage tree found in the rendered page")
    for key, _n, unit in nodes:
        if not unit:
            raise Violation("tree-units",
                            f"tree node {key!r} declares no data-unit — the strip this replaced "
                            f"mixed vendors and rows in one row of numbers, unlabelled")

    expected = {}

    def _walk(ns):
        for node in ns:
            expected[node["key"]] = node["n"]
            if node["children"]:
                kids = [c["n"] for c in node["children"]]
                if node["n"] is not None and all(k is not None for k in kids):
                    if sum(kids) != node["n"]:
                        raise Violation(
                            "tree-sums",
                            f"{node['key']}={node['n']} but its children sum to {sum(kids)}")
            _walk(node["children"])

    _walk(_tree.build(payload))

    for key, n, _u in nodes:
        if key in expected and expected[key] != n:
            raise Violation("tree-payload",
                            f"tree node {key!r} renders {n}, but drift.json says "
                            f"{expected[key]} — the tree is a projection, not a decoration")
    # re-derive the sums from the RENDERED attributes too, so a hand-edited page fails even
    # when the builder would have produced the right answer
    rendered = {k: n for k, n, _ in nodes}
    for parent, kids in (("detected", ("integrations", "assets")),
                         ("integrations", ("tracked", "queued", "needs-human", "blocked"))):
        pv = rendered.get(parent)
        kv = [rendered[k] for k in kids if k in rendered]
        if pv is not None and kv and all(v is not None for v in kv) and sum(kv) != pv:
            raise Violation("tree-sums",
                            f"rendered {parent}={pv} but its children sum to {sum(kv)}")


def check_tree_parity(html: str, md_text: str) -> None:
    """The ASCII tree in drift.md and the <ul> tree in the page carry the same numbers.

    Both come from one builder, so a divergence means a RENDERER is lying — which is exactly the
    failure a reader cannot detect, since they will only ever look at one of the two surfaces.
    """
    rendered = [(k, n) for k, n, _ in _tree_nodes(html) if n is not None]
    for key, n in rendered:
        if f"{n} {key.replace('-', ' ')}" not in md_text and f"{n} {key}" not in md_text:
            raise Violation("tree-parity",
                            f"the HTML tree says {key}={n}, which does not appear in drift.md — "
                            f"one renderer disagrees with the other")
```

- [ ] **Step 4: Register them in the verify command**

In `agent/cli.py`, in the verify command's `checks` list (around line 500), add:

```python
              (_verify.check_tree_matches_payload, (html, payload)),
              (_verify.check_tree_parity, (html, drift_md)),
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_verify_tree.py -q` → PASS (6 tests).
Then the full suite.

Then prove it end-to-end from a NEUTRAL cwd:

```bash
cd /tmp && DRIFT_CATALOG_DIR=$HOME/.drift/catalog \
  /home/tops/Projects/tops/drift/drift-detector-scan/bin/drift-scan run \
  --root /home/tops/Projects/sandbox/promoteplus-crm --state /tmp/tree-e2e --now 2026-08-13
cd /tmp && /home/tops/Projects/tops/drift/drift-detector-scan/bin/drift-scan verify --state /tmp/tree-e2e
```
Expected: exit 0. Then hand-edit one `data-n` in `/tmp/tree-e2e/dashboard.html`, re-run `verify`,
confirm it fails naming `tree-sums` or `tree-payload`, and restore. Record both outputs.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/verify.py agent/cli.py tests/test_verify_tree.py
git commit -m "feat(verify): the coverage tree is a proven projection, not a decoration"
```

---

### Task 5: definitions under the tree

**Files:**
- Modify: `agent/lib/tree.py` (a `DEFINITIONS` map + emit a `<details>`)
- Modify: `agent/lib/verify.py` (`check_tree_definitions`)
- Test: `tests/test_tree_definitions.py`

**Interfaces:**
- Consumes: `tree.build`, `tree.html_tree`.
- Produces: `tree.DEFINITIONS: dict[str, str]` and `tree.html_definitions(nodes) -> str`.
  `verify.check_tree_definitions(html: str) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tree_definitions.py`:

```python
import pytest
from agent.lib import tree, verify


def _payload():
    return {"counts": {"detected": 73, "integrations": 30, "excluded": 43, "apis": 21,
                       "coverage": {"tracked": 27, "queued": 3, "needs-human": 0,
                                    "blocked": 0, "na": 43},
                       "hostClasses": {"boilerplate": 20}}}


def test_every_node_has_a_definition():
    """The page's two load-bearing words — `queued` and `unaudited` — carried the whole honesty
    argument as bare numbers. The owner came back after a week and could not remember them."""
    nodes = tree.build(_payload())
    keys = set()

    def walk(ns):
        for n in ns:
            keys.add(n["key"]); walk(n["children"])
    walk(nodes)
    missing = sorted(k for k in keys if k not in tree.DEFINITIONS)
    assert not missing, missing


def test_definitions_render_as_a_details_block():
    html = tree.html_definitions(tree.build(_payload()))
    assert "<details" in html and "What these mean" in html
    assert 'data-def="queued"' in html


def test_a_node_without_a_definition_is_a_violation():
    html = tree.html_tree(tree.build(_payload())) + tree.html_definitions(tree.build(_payload()))
    verify.check_tree_definitions(html)
    broken = html.replace('data-def="queued"', 'data-def="quued"')
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_definitions(broken)
    assert e.value.check == "tree-definitions"
```

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_tree_definitions.py -q`
Expected: FAIL — `DEFINITIONS` does not exist.

- [ ] **Step 3: Add the definitions and the renderer**

Append to `agent/lib/tree.py`:

```python
# Every node key needs an entry; verify.check_tree_definitions enforces it, so the glossary
# cannot drift from the numbers it explains. Written for someone who has been away a week.
DEFINITIONS = {
    "detected": "Every outbound endpoint the scan read. The complete inventory — everything "
                "below is a filter over this, never a gate that hides a row.",
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
}


def html_definitions(nodes: list) -> str:
    """A <details> glossary keyed to the tree's nodes. Not tooltips: those are neither
    discoverable nor checkable from source, and this page cannot be checked any other way."""
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
```

Add to `agent/lib/verify.py`:

```python
def check_tree_definitions(html: str) -> None:
    """Every tree node has a glossary entry on the same page.

    `queued` and `unaudited` carry this tool's entire honesty argument — "0 findings here is not
    evidence of clean" — and shipped as bare numbers. A definition that silently stops matching
    its node is the same failure one step later, so the pairing is asserted rather than trusted.
    """
    nodes = {k for k, _n, _u in _tree_nodes(html)}
    defined = set(re.findall(r'data-def="([^"]*)"', html))
    missing = sorted(nodes - defined)
    if missing:
        raise Violation("tree-definitions",
                        f"tree node(s) {missing} have no definition on the page")
```

Emit it next to the tree in `dashboard_render.render_payload`:

```python
         '<section id="coverage-tree">' + _tree.html_tree(_tree.build(projection))
         + _tree.html_definitions(_tree.build(projection)) + '</section>',
```

Register in `agent/cli.py`'s checks list: `(_verify.check_tree_definitions, (html,)),`

- [ ] **Step 4: Run and confirm**

Run: `.venv/bin/python -m pytest tests/test_tree_definitions.py -q` → PASS.
Then the full suite.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/tree.py agent/lib/verify.py agent/lib/dashboard_render.py agent/cli.py \
        tests/test_tree_definitions.py
git commit -m "feat(tree): definitions that cannot drift from the numbers they explain"
```

---

## Stage 2 — collapse the planes

### Task 6: Vendor Drift becomes the page; Supply Chain drops a level

**Files:**
- Modify: `agent/assets/dashboard.app.js` (plane state, default view, deep-link mapping)
- Modify: `agent/assets/dashboard.template.html` (plane cards → section nav)
- Test: `tests/test_dashboard_sections.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no Python interface. The `plane` state keeps its name to avoid churn in
  `check_accessor_coverage`'s allowed accessors.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard_sections.py`:

```python
from pathlib import Path

_A = Path(__file__).resolve().parent.parent / "agent" / "assets"


def test_there_is_no_ai_plane_card():
    """The AI plane was misfiled, not unused: `research` is coverage-lifecycle progress (a
    property of the tracking column) and `shaped`/`leads` are findings with weaker provenance.
    A column and a badge had been promoted to a peer of the product."""
    tpl = (_A / "dashboard.template.html").read_text()
    assert 'plane="ai"' not in tpl
    assert "AI Frontier" not in tpl


def test_vendor_drift_is_the_default_view():
    js = (_A / "dashboard.app.js").read_text()
    assert 'plane: "drift"' in js or "plane:'drift'" in js


def test_the_ai_deep_link_still_resolves():
    """?plane=ai was a shareable URL. It must land somewhere sensible, not fall through to a
    blank view."""
    js = (_A / "dashboard.app.js").read_text()
    assert '"ai"' in js and "drift" in js


def test_supply_chain_survives_as_a_section():
    tpl = (_A / "dashboard.template.html").read_text()
    assert "Supply Chain" in tpl


def test_the_timeline_keeps_both_lanes():
    """check_timeline_lanes greps for these; a restructure that drops the undated lane makes a
    `deprecated-no-date` sunset render nowhere while the tile stays green."""
    tpl = (_A / "dashboard.template.html").read_text()
    assert "timeline.dated" in tpl and "timeline.undated" in tpl
```

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard_sections.py -q`
Expected: FAIL on the first two — the AI plane card and `AI Frontier` string are still present.

- [ ] **Step 3: Make the change**

In `dashboard.app.js`: remove the `{key:"ai", ...}` entry from the plane-cards list and the `ai`
tile group; default `plane` to `"drift"`; and map a legacy `?plane=ai` to `"drift"` so old links
resolve. In `dashboard.template.html`: delete the AI Frontier card, keep Supply Chain as a section
below Vendor Drift, and leave both `timeline.dated` / `timeline.undated` bindings untouched.

Do NOT delete the AI tier RENDERING (the shaped/leads/research sections) — Task 7 relocates it.

- [ ] **Step 4: Run and confirm**

Run: `.venv/bin/python -m pytest tests/test_dashboard_sections.py -q` → PASS.
Then the full suite — `check_timeline_lanes` and `check_accessor_coverage` both read these files.

- [ ] **Step 5: Commit**

```bash
git add agent/assets tests/test_dashboard_sections.py
git commit -m "refactor(dashboard): Vendor Drift is the page; Supply Chain is a section"
```

---

### Task 7: AI folds in as provenance

**Files:**
- Modify: `agent/assets/dashboard.template.html`, `agent/assets/dashboard.app.js`
- Test: `tests/test_dashboard_provenance.py`

**Interfaces:**
- Consumes: the `leads-data` / `adhoc-data` / `research-data` blobs, unchanged.
- Produces: no Python interface. A render-time join keyed on vendor/host.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard_provenance.py`:

```python
from pathlib import Path

_A = Path(__file__).resolve().parent.parent / "agent" / "assets"


def test_the_three_provenance_badges_survive_the_move():
    tpl = (_A / "dashboard.template.html").read_text()
    for badge in ("GATE-VALIDATED", "SOURCED", "UNVERIFIED LEAD"):
        assert badge in tpl, badge


def test_a_lead_is_never_labelled_certified():
    tpl = (_A / "dashboard.template.html").read_text()
    i = tpl.find("UNVERIFIED LEAD")
    assert i != -1 and "CERTIFIED" not in tpl[i:i + 400]


def test_research_status_renders_on_the_lifecycle_not_as_a_tab():
    js = (_A / "dashboard.app.js").read_text()
    assert "researchStatus" in js


def test_never_run_is_distinct_from_found_nothing():
    """Absent is not zero. 'Research has never run' and 'research ran and found nothing' are
    different facts and the page must not collapse them."""
    js = (_A / "dashboard.app.js").read_text()
    assert "never run" in js


def test_certified_counts_do_not_read_ai_blobs():
    """The firewall's presentation counterpart: a visual join must never let a shaped or lead
    count into a certified total."""
    js = (_A / "dashboard.app.js").read_text()
    for i, line in enumerate(js.splitlines(), 1):
        if "c.detected" in line or "c.integrations" in line:
            assert "LEADS" not in line and "ADHOC" not in line, f"line {i}: {line}"
```

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard_provenance.py -q`
Expected: FAIL on `researchStatus` / `never run`.

- [ ] **Step 3: Make the change**

Move the shaped rows into the findings table with their `GATE-VALIDATED` badge; keep leads as a
marked subsection with `UNVERIFIED LEAD`; add a `researchStatus` computed that reports when the
last research pass ran and what it covered, or the literal string `never run` when `RESEARCH` is
null. Render it as a suffix on the queued row. A research `retiring` verdict must carry both its
badge and a "not in catalog yet" suffix so it cannot read as a certified sunset.

Rewrite the tier legend and footer copy that name "the AI Frontier plane".

- [ ] **Step 4: Run and confirm**

Run: `.venv/bin/python -m pytest tests/test_dashboard_provenance.py -q` → PASS. Then the full suite.

Then prove the firewall still holds end-to-end: run a scan, inject `"origin": "ai"` into an
endpoint of `drift.json`, run `verify`, confirm `ai-firewall` fires, restore.

- [ ] **Step 5: Commit**

```bash
git add agent/assets tests/test_dashboard_provenance.py
git commit -m "refactor(dashboard): AI becomes provenance on the vendor row, not a destination"
```

---

### Task 8: retire the mixed tile strip

**Files:**
- Modify: `agent/assets/dashboard.app.js`, `agent/assets/dashboard.template.html`
- Test: `tests/test_dashboard_sections.py`

**Interfaces:** consumes Tasks 3 and 6; no Python interface.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dashboard_sections.py`:

```python
def test_the_mixed_unit_tile_row_is_gone():
    """It counted distinct VENDORS in `Tracked` and endpoint ROWS in its neighbours, so it summed
    to 67 against a Detected of 73. The tree replaces it and every node is in rows."""
    js = (_A / "dashboard.app.js").read_text()
    assert 'label:"Detected"' not in js
    assert 'label:"Tracked"' not in js
    assert 'label:"Assets"' not in js


def test_the_findings_tiles_keep_their_context():
    """Sunsets/Past-due are ACTION counts and stay with the timeline; Unaudited/Private are
    'cannot see' content and stay in the coverage footer."""
    tpl = (_A / "dashboard.template.html").read_text()
    assert "Unaudited" in tpl and "Past-due" in tpl
```

- [ ] **Step 2: Run, watch it fail, remove the tiles, confirm**

Run: `.venv/bin/python -m pytest tests/test_dashboard_sections.py -q` — fails while the labels
remain. Remove the `detected`/`apis`/`unknown`/`excluded` tiles from the drift plane's tile group;
move `sunsets`/`pastDue` into the timeline header and `unaudited`/`private` into the coverage
footer. Re-run → PASS, then the full suite.

- [ ] **Step 3: Commit**

```bash
git add agent/assets tests/test_dashboard_sections.py
git commit -m "refactor(dashboard): retire the tile strip whose numbers never summed"
```

---

### Task 9: the firewall's presentation counterpart

**Files:**
- Modify: `agent/lib/verify.py` (`check_tree_certified_only`)
- Test: `tests/test_verify_tree.py`

**Interfaces:** consumes Task 4's `_tree_nodes`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_verify_tree.py`:

```python
def test_a_tree_node_inflated_beyond_the_certified_counts_is_a_violation():
    """The real risk of a VISUAL merge: someone folds shaped call-sites or leads into a tree node
    so the page looks fuller. The data blobs stay separate — this stops the NUMBERS merging."""
    p = _payload()
    html = tree.html_tree(tree.build(p)).replace('data-node="detected" data-n="73"',
                                                 'data-node="detected" data-n="80"')
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_certified_only(html, p)
    assert e.value.check == "tree-certified-only"


def test_a_faithful_tree_passes_the_certified_check():
    verify.check_tree_certified_only(tree.html_tree(tree.build(_payload())), _payload())
```

- [ ] **Step 2: Run, watch it fail, implement, confirm**

Add to `agent/lib/verify.py`:

```python
def check_tree_certified_only(html: str, payload: dict) -> None:
    """No tree number may exceed what the CERTIFIED payload supports.

    The AI tiers now render inside Vendor Drift instead of a plane of their own. That is a visual
    join — the blobs stay separate and check_ai_firewall keeps the data apart — but a visual join
    tempts a future edit to add shaped or lead counts into a tree node so the page looks fuller.
    A count sourced from an unverified tier, displayed with the authority of a certified one, is
    precisely the confusion this tool exists to prevent.
    """
    detected = ((payload.get("counts") or {}).get("detected"))
    if detected is None:
        return
    for key, n, _u in _tree_nodes(html):
        if n is not None and n > detected:
            raise Violation("tree-certified-only",
                            f"tree node {key!r}={n} exceeds certified detected={detected} — a "
                            f"non-certified count has been folded into the tree")
```

Register it in `agent/cli.py`'s checks list. Run the tests, then the full suite.

- [ ] **Step 3: Commit**

```bash
git add agent/lib/verify.py agent/cli.py tests/test_verify_tree.py
git commit -m "feat(verify): tree numbers may only come from certified data"
```

---

## Stage 3 — research runs itself

### Task 10: `research.auto`, on by default

**Files:**
- Modify: `commands/drift-detector.md` (the promptfile runs research as part of the flow)
- Modify: `agent/cli.py` (a `research.auto` config read, default true)
- Test: `tests/test_research_auto.py`

**Interfaces:**
- Produces: config key `research.auto` (default `true`). When false, the promptfile skips the pass.

**Owner's decision, recorded:** research runs on every scan, unprompted and **uncapped**. This
overrides both the advisory review and the implementing agent's recommendation. The accepted
tradeoff: every scan spends tokens without asking, and a fleet scan spends per repo. The
mitigations are disclosure (Task 11) and the opt-out switch below — not a prompt.

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_auto.py`:

```python
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_the_promptfile_runs_research_without_asking():
    """The owner's instruction: 'we don't have to bother the user by constantly asking for it,
    we just have to give the end result.'"""
    main = (_ROOT / "commands" / "drift-detector.md").read_text()
    assert "research" in main
    assert "do NOT ask" in main or "without asking" in main


def test_the_opt_out_exists_for_ci():
    main = (_ROOT / "commands" / "drift-detector.md").read_text()
    assert "research.auto" in main


def test_the_token_cost_is_stated_not_hidden():
    """Spending without asking is the decision; spending without SAYING would be dishonest."""
    main = (_ROOT / "commands" / "drift-detector.md").read_text()
    i = main.find("research")
    assert "token" in main[max(0, i - 2000):i + 2000].lower()
```

- [ ] **Step 2: Run, watch it fail, wire it, confirm**

Run the test, watch it fail. Then rewrite the promptfile's scan flow so the research pass fires
automatically after the deterministic scan — no gate, no question — reading `research.auto` and
skipping only when explicitly false. State the token cost in the same up-front line that already
discloses the AI plane's cost. Re-run → PASS, then the full suite.

- [ ] **Step 3: Commit**

```bash
git add commands/drift-detector.md agent/cli.py tests/test_research_auto.py
git commit -m "feat(research): runs on every scan, unprompted (owner's call, uncapped)"
```

---

### Task 11: the queued node discloses what research did

**Files:**
- Modify: `agent/lib/tree.py` (research suffix on the queued node)
- Test: `tests/test_tree.py`

**Interfaces:** consumes `research.json` via the payload or a passed-in argument — read how
`run.py` already loads it and follow that, rather than reading the file inside `tree.py` (the
builder must stay pure).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tree.py`:

```python
def test_queued_says_when_research_last_ran():
    p = _payload()
    nodes = tree.build(p, research={"checked": "2026-08-13", "researched": 4})
    f = _flat(nodes)
    assert "2026-08-13" in f["queued"]["note"] and "4" in f["queued"]["note"]


def test_queued_says_never_run_rather_than_implying_a_clean_pass():
    """'Research found nothing' and 'research never ran' are different facts. Collapsing them is
    exactly the 'cannot see' = 'clean' failure this tool refuses."""
    f = _flat(tree.build(_payload(), research=None))
    assert "never run" in f["queued"]["note"]
```

- [ ] **Step 2: Run, watch it fail, implement, confirm**

Give `build` an optional `research: dict | None = None` keyword; append the suffix to the queued
node's note. Keep `build` pure — the caller supplies the dict. Update
`dashboard_render`/`md_render` to pass it through. Re-run, then the full suite.

- [ ] **Step 3: Commit**

```bash
git add agent/lib/tree.py agent/lib/dashboard_render.py agent/lib/md_render.py tests/test_tree.py
git commit -m "feat(tree): the queued node states when research last ran, or that it never did"
```

---

### Task 12: end-to-end proof

**Files:** no source changes; appends a `## Result` section to this plan.

- [ ] **Step 1: Scan the reference repo from a NEUTRAL cwd**

```bash
cd /tmp && DRIFT_CATALOG_DIR=$HOME/.drift/catalog \
  /home/tops/Projects/tops/drift/drift-detector-scan/bin/drift-scan run \
  --root /home/tops/Projects/sandbox/promoteplus-crm --state /tmp/reframe-e2e --now 2026-08-13
```

- [ ] **Step 2: Record the measurements**

1. `verify --state /tmp/reframe-e2e` exits 0.
2. The ASCII tree appears in `drift.md` and its arithmetic balances against `drift.json`.
3. `grep -c 'data-node=' /tmp/reframe-e2e/dashboard.html` is non-zero; no `<pre>` tree.
4. The page renders the tree with JS disabled — confirm by checking the fragment contains no
   `v-for` / `{{` / `@click` bindings.
5. Each guard bites: hand-edit a `data-n` → `tree-sums`/`tree-payload` fires; remove a
   `data-def` → `tree-definitions` fires; inflate a node past `detected` →
   `tree-certified-only` fires. Restore after each and confirm green.
6. `?plane=ai` resolves to the Vendor Drift view.
7. Research ran without being asked, and the queued node says so.

- [ ] **Step 3: Append the `## Result` section and commit**

Record the real numbers and anything that did not go as expected. Do not adjust code to make a
measurement look better — report it.

---

## Self-review

**Spec coverage:** IA reframe → Tasks 6-8. Tree as machine-checked header → Tasks 1, 3, 4. One
builder / two projections → Tasks 1-4 (`tree-parity` in Task 4). Unit fix → Tasks 1, 8. Definitions
→ Task 5. Auto-research → Tasks 10-11. Firewall preservation → Tasks 7, 9. Risks (timeline lanes,
accessor names, deep links, legend copy) → Tasks 6, 7. Stage-1-first ordering matches the spec.

**Placeholder scan:** none. Tasks 6, 7, 8, 10 describe edits to existing front-end files without
reproducing the whole file — deliberate, since the surrounding markup is large and the tests pin
the required outcome exactly. Every new module and every invariant carries complete code.

**Type consistency:** `tree.build(payload, research=None) -> list` of
`{key,label,n,unit,note,children}` is defined in Task 1, extended in Task 11, and consumed by
`md_tree`/`html_tree`/`html_definitions` (Tasks 2, 3, 5) and by `verify._tree_nodes` (Task 4).
`Violation` check names — `tree-sums`, `tree-payload`, `tree-units`, `tree-parity`,
`tree-definitions`, `tree-certified-only` — are used identically in implementations and tests.

---

## Task 5b: `summary.html` — the bare-bones page (inserted after Stage 1)

**Origin:** the owner opened the Stage 1 output and found the tree appended at the BOTTOM of the
cockpit, underneath the very tile strip it replaces. That placement was a plan error — Task 3 said
to inject "immediately after `TEMPLATE_SRC`", written thinking of position relative to the data
blobs, but `TEMPLATE_SRC` is the entire page, so "after" meant "below everything".

Asked where the tree should actually live, the owner chose a **separate bare-bones page** over
fixing the placement in the cockpit. That is the stronger answer: the tree's whole value is being
readable in seconds, and loading a Vue application to read twelve numbers is at odds with that.

**The end state, three surfaces from one builder:**

| surface | what it is |
|---|---|
| `drift.md` | the report, with the ASCII tree — readable with no browser at all |
| `summary.html` | **the default view**: tree + glossary + headline numbers. Pure HTML, no Vue, no JS |
| `dashboard.html` | the detailed cockpit — tables, timeline, SBOM/SARIF. The drill-down |

**Files:**
- Create: `agent/lib/summary_render.py`, `agent/assets/summary.css`
- Modify: `agent/lib/dashboard_render.py` (REMOVE the `#coverage-tree` section), `agent/run.py`
  (write `summary.html`), `agent/cli.py` (point the tree checks at `summary.html`)
- Test: `tests/test_summary_page.py`

**Requirements:**
1. `summary_render.render_summary(payload, now) -> str` emits a complete, self-contained HTML
   document: the coverage tree, the glossary, and the headline numbers (fixes, sunsets, past-due,
   unaudited). It embeds its own CSS inline and loads **no** JavaScript whatsoever — not Vue, not a
   snippet. If the page needs JS to be correct it is not a projection.
2. **The `├─` / `└─` connectors are drawn in CSS**, via pseudo-elements, so the HTML reads like the
   ASCII tree. They are decoration over the `<ul>` structure, never content — the numbers still
   live in `data-n`, so a connector cannot lie about arithmetic.
3. The tree section is REMOVED from `dashboard.html`. One tree per surface; the cockpit keeps its
   own tables.
4. `verify`'s tree checks (`tree-sums`, `tree-payload`, `tree-units`, `tree-text-mismatch`,
   `tree-parity`, `tree-node-set`, `tree-definitions`, `tree-missing`) now run against
   `summary.html`. They must keep firing on every tamper they already catch — that coverage was
   proven end-to-end and must not regress in the move.
5. Deterministic and self-contained: same payload → byte-identical page, and it must render with
   both JavaScript and network access entirely absent.

**Knock-on for Stage 2:** the tree is no longer the cockpit's header, so Task 6 keeps the plane
collapse and Task 8 keeps retiring the mixed tile strip (its unit bug is real regardless of where
the tree lives), but neither needs to restructure around the tree. Task 9's
`tree-certified-only` moves to `summary.html` with the other tree checks.

---

## Task 5c: the tree carries its rows (inserted after 5b)

**Origin:** the owner saw `summary.html` and asked to see the actual data in the tree, not just
counts. Chosen depth: **hosts, each expanding to its `file:line` locations.**

This is not decoration. Today a node CLAIMS "20 boilerplate"; with rows it SHOWS twenty hosts that
must each exist in `drift.json`. The tree stops being self-consistent and starts being
self-evidencing — and it puts the product's actual claim, *down to `file:line`*, on the default view.

**Files:**
- Modify: `agent/lib/tree.py` (rows on each node; render them in `html_tree`)
- Modify: `agent/lib/summary_render.py` if the rows need styling hooks; `agent/assets/summary.css`
- Modify: `agent/lib/verify.py` (new `check_tree_rows`), `agent/cli.py` (register it)
- Test: `tests/test_tree_rows.py`

**Requirements:**

1. **Rows are HTML-only.** `md_tree` keeps emitting counts alone — `drift.md` must not balloon with
   176 file locations. `build()` may attach the rows; the ASCII renderer ignores them.

2. **Rows must not break `tree-parity` or `tree-node-set`.** Those checks find nodes by the
   `data-node` attribute and compare the HTML node sequence against the ASCII tree. Row elements
   must therefore carry a DIFFERENT attribute (`data-row`, `data-loc`) and never `data-node`, so the
   existing parsers skip them. Verify both invariants still pass unchanged — they were hard-won.

3. **Native `<details>`/`<summary>` only. Still zero JavaScript.** A node expands to its hosts; a
   host expands to its locations. No `<script>`, no handlers.

4. **What each row shows.** Host; for `tracked` rows also the vendor, version and the vendor's
   catalog verdict (joined from `payload["catalog"]` — `UNAUDITED` here is the honesty surface and
   must be visible); for `queued` rows the reason where present (`ownInfraReason`); call-site count
   for all.

5. **`files[]` IS TRUNCATED and the page must say so.** Measured on the reference repo: 16 of 73
   endpoints carry fewer locations than their `file_count` (`www.googleapis.com` reports 45
   call-sites but only 20 locations). Rendering the short list unqualified would state "here is
   where it is called" while hiding 25 of them — "cannot see" presented as "clean", on the surface
   built to refuse exactly that. Every truncated row must read *showing 20 of 45*.

6. **New invariant `check_tree_rows(html, payload)`:** for every node with rows, the number of
   rendered rows equals that node's `data-n`; every rendered host exists in `drift.json`'s endpoints
   for that node's bucket; and no row is invented. Prove it fails on a deleted row, an added row,
   and a renamed host.

7. Escape everything — file paths and hostnames both derive from scanned source. Deterministic
   ordering (never by count); same payload → byte-identical page.

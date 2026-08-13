import re

import pytest
from agent.lib import tree, verify


def _payload():
    return {"counts": {"detected": 73, "integrations": 30, "excluded": 43, "apis": 21,
                       "coverage": {"tracked": 27, "queued": 3, "needs-human": 0,
                                    "blocked": 0, "na": 43},
                       "hostClasses": {"boilerplate": 20, "social-widget": 12,
                                       "vendored-lib": 5, "asset-cdn": 3, "own-infra": 5}}}


def _payload_with_assets():
    """`_payload()` has no `endpoints`, so `tree.build` renders `assets` CHILDLESS (see
    `test_assets_render_childless_rather_than_wrong_without_endpoints` in test_tree.py) — the
    assets→hostClass level of the tree is never exercised by any existing verify test. This
    fixture wires in real endpoint rows so that level actually has children (20+12+5+3+3=43,
    matching counts.excluded), which is the exact level Finding 1's hardcoded pair list never
    summed from the markup at all."""
    p = _payload()
    p["endpoints"] = ([{"hostClass": "boilerplate", "coverage": "na"} for _ in range(20)] +
                      [{"hostClass": "social-widget", "coverage": "na"} for _ in range(12)] +
                      [{"hostClass": "vendored-lib", "coverage": "na"} for _ in range(5)] +
                      [{"hostClass": "asset-cdn", "coverage": "na"} for _ in range(3)] +
                      [{"hostClass": "own-infra", "coverage": "na"} for _ in range(3)])
    return p


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


def test_parity_catches_a_hyphenated_hostclass_label_mismatch():
    """Regression for the brief's original `f"{n} {key.replace('-', ' ')}"` heuristic: an asset
    hostClass key like `social-widget` renders with the HYPHEN kept (it is not in _LABELS, so its
    label is the raw key), not turned into a space. A parity check that guesses the space form
    would either false-flag a correct render or (worse) never actually compare the real text. This
    asserts the real end-to-end case round-trips clean, and that corrupting the ASCII line's number
    is still caught even for a hyphenated-key node deep in the assets subtree."""
    p = _payload()
    p["endpoints"] = [{"hostClass": "social-widget", "coverage": "na"} for _ in range(12)] + \
                      [{"hostClass": "boilerplate", "coverage": "na"} for _ in range(20)] + \
                      [{"hostClass": "vendored-lib", "coverage": "na"} for _ in range(5)] + \
                      [{"hostClass": "asset-cdn", "coverage": "na"} for _ in range(3)] + \
                      [{"hostClass": "own-infra", "coverage": "na"} for _ in range(3)]
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    good_md = "\n".join(tree.md_tree(nodes))
    verify.check_tree_parity(html, good_md)  # must pass — this IS the faithful render
    bad_md = good_md.replace("12 social-widget", "11 social-widget")
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_parity(html, bad_md)
    assert e.value.check == "tree-parity"


def test_needs_human_node_parity():
    """The needs-human node's label is `needs human` (a space, from _LABELS), not the raw
    `needs-human` key — parity must compare against what _fmt actually produced, not a guess."""
    p = _payload()
    p["counts"]["coverage"]["needs-human"] = 2
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    good_md = "\n".join(tree.md_tree(nodes))
    verify.check_tree_parity(html, good_md)
    bad_md = good_md.replace("2 needs human", "3 needs human")
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_parity(html, bad_md)
    assert e.value.check == "tree-parity"


def test_null_count_node_parity():
    """A predates-lifecycle scan renders `not counted (integrations)` with no number at all —
    parity must still catch a divergence in that text, not skip null nodes as if they don't exist."""
    p = _payload(); del p["counts"]["coverage"]
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    good_md = "\n".join(tree.md_tree(nodes))
    verify.check_tree_parity(html, good_md)
    bad_md = good_md.replace("not counted (integrations)", "not counted (unknown)")
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_parity(html, bad_md)
    assert e.value.check == "tree-parity"


# ---------------------------------------------------------------------------------------
# Finding 1 (CRITICAL, review round 1): a trailing run of deleted <li>s was a false green.
# The hardcoded pair list in check_tree_matches_payload only knew about
# detected->(integrations,assets) and integrations->(tracked,queued,needs-human,blocked); the
# assets->hostClass level was never summed from the rendered markup at all, and
# check_tree_parity indexed HTML nodes into the ASCII lines positionally, so an HTML tree that
# simply stopped early ran out of nodes to compare before the leftover ASCII lines were ever
# looked at. Reproduced end-to-end through the real CLI (see task-4-report.md, "Fix round 1").
# ---------------------------------------------------------------------------------------

def test_a_faithful_tree_with_asset_children_still_passes():
    """Positive control for the fix: once assets->hostClass actually HAS children (a real
    scan's endpoints), the new nested, every-depth sum derivation must still pass on an honest
    render. A fix that closes the hole must not open a false RED in its place."""
    p = _payload_with_assets()
    nodes = tree.build(p)
    verify.check_tree_matches_payload(tree.html_tree(nodes), p)
    verify.check_tree_parity(tree.html_tree(nodes), "\n".join(tree.md_tree(nodes)))


def test_deleting_the_trailing_asset_child_breaks_the_assets_level_sum():
    """The exact reproduction: deleting ONE trailing <li> (`own-infra`, the last node in the
    whole document — last child of `assets`, itself the second and final child of `detected`)
    leaves `assets` displaying 43 while its four remaining children sum to 40. The OLD
    hardcoded pair list had no entry for this level at all, so this was a false green; the
    rendered-nesting-derived sum check must catch it at ANY depth, not just the two levels the
    pair list happened to name."""
    p = _payload_with_assets()
    html = tree.html_tree(tree.build(p))
    # DOTALL + non-greedy: own-infra's <li> now carries its own rows (task 5c) after the `.tc`
    # span, but a leaf's rows are emitted as `<div>`s, never `<li>` (see tree.py's `_row_html`),
    # so the first `</li>` reached after own-infra's OPEN tag is still, unambiguously, its own.
    trimmed = re.sub(r'<li data-node="own-infra"[^>]*>.*?</li>',
                     "", html, count=1, flags=re.S)
    assert trimmed != html, "the test's own regex did not remove the trailing <li>"
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(trimmed, p)
    assert e.value.check == "tree-sums"


def test_deleting_all_asset_children_is_caught_by_node_count_parity():
    """The other half of the same reproduction: deleting ALL FIVE asset children (not just
    one) leaves `assets`'s own <li> untouched — still `data-n="43"` — with no children left to
    sum against at all, so the sum check has nothing to compare. What must catch it is
    check_tree_parity's node-count assertion: the HTML tree now has 5 fewer nodes than the
    (untouched, honest) ASCII tree in drift.md, and that truncation has to fail loudly instead
    of the parity loop simply running out of HTML nodes to index against."""
    p = _payload_with_assets()
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    good_md = "\n".join(tree.md_tree(nodes))
    for hc in ("boilerplate", "social-widget", "vendored-lib", "asset-cdn", "own-infra"):
        # DOTALL + non-greedy: each leaf now carries its own rows (task 5c) as `<div>`s (never
        # `<li>`), so the first `</li>` after a leaf's OPEN tag is still, unambiguously, its own.
        html, n = re.subn(rf'<li data-node="{hc}"[^>]*>.*?</li>',
                          "", html, count=1, flags=re.S)
        assert n == 1, f"the test's own regex did not remove the {hc!r} <li>"
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_parity(html, good_md)
    assert e.value.check == "tree-parity"


def test_deleting_a_whole_ul_subtree_is_caught_by_node_count_parity():
    """A structurally different deletion from the one above: removing the entire wrapping
    `<ul>...</ul>` for assets' children in one cut (as a stack-based `<li>`/`<ul>` parse would
    see it — a whole subtree popped at once) rather than five individual `<li>` removals. Must
    be caught the same way: the rendered tree has fewer nodes than the ASCII tree names."""
    p = _payload_with_assets()
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    good_md = "\n".join(tree.md_tree(nodes))
    gutted, n = re.subn(
        r'(<li data-node="assets"[^>]*><span class="tc">[^<]*</span>)<ul>.*?</ul>(</li>)',
        r"\1\2", html, count=1, flags=re.S)
    assert n == 1, "the test's own regex did not remove the assets subtree"
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_parity(gutted, good_md)
    assert e.value.check == "tree-parity"


# ---------------------------------------------------------------------------------------
# Finding 2 (Minor, review round 1): visible text was never bound to data-n.
# ---------------------------------------------------------------------------------------

def test_visible_text_disagreeing_with_data_n_is_a_violation():
    """Editing the displayed text in BOTH surfaces consistently ('73 detected' -> '999
    detected') while `data-n="73"` stays honest passed every prior check: blob-parity never
    looks at this markup, tree-sums and tree-payload both compare the `data-n` ATTRIBUTE, never
    the digits a reader actually sees. Only a check binding the visible text to its own node's
    data-n + known label catches it."""
    p = _payload()
    html = tree.html_tree(tree.build(p))
    tampered = html.replace(">73 detected<", ">999 detected<", 1)
    assert tampered != html
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(tampered, p)
    assert e.value.check == "tree-text-mismatch"


# ---------------------------------------------------------------------------------------
# Fix round 2 — the Important finding: the rendered node SET was never compared to the
# payload's node set. Every existing check above either (a) walks the RENDERED nodes and
# skips any key not in `expected` (the per-node value loop `continue`s), or (b) sums
# RENDERED children against their RENDERED parent (nothing to sum if the children are simply
# ABSENT, not merely wrong). Both tampers below were verified against a real report and
# BOTH exited 0, "all agree", before this fix. The reproductions here call
# check_tree_matches_payload ALONE (no check_tree_parity, no drift.md at all) because the
# fix must make that one check stand on its own — a caller of only this function must not
# be able to be fooled the way it could before.
# ---------------------------------------------------------------------------------------

def test_symmetric_deletion_of_all_asset_children_is_caught_by_matches_payload_alone():
    """Tamper #1 from the finding: delete all five asset hostClass <li>s. `assets` keeps its
    own data-n="43" with no children left, so the sums check has nothing to sum, and the
    per-node loop below only ever visits RENDERED keys — the five deleted keys are simply
    never looked at by anything. This used to pass check_tree_matches_payload outright; the
    node-set/order comparison must catch it without needing check_tree_parity's help."""
    p = _payload_with_assets()
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    for hc in ("boilerplate", "social-widget", "vendored-lib", "asset-cdn", "own-infra"):
        # DOTALL + non-greedy: see the comment in the node-count-parity version of this tamper
        # above — a leaf's own rows (task 5c) are `<div>`s, never `<li>`, so this still removes
        # exactly one node's own markup, nothing more.
        html, n = re.subn(rf'<li data-node="{hc}"[^>]*>.*?</li>',
                          "", html, count=1, flags=re.S)
        assert n == 1, f"the test's own regex did not remove the {hc!r} <li>"
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(html, p)
    assert e.value.check == "tree-node-set"


def test_symmetric_insertion_of_a_phantom_node_is_caught_by_matches_payload_alone():
    """Tamper #2 from the finding: add a fabricated <li data-node="phantom" data-n="3" ...>
    under the own-infra leaf. own-infra's own data-n stays 3 (now the sum of its one child,
    so the sums check balances), and 'phantom' is not a key in `expected`, so the per-node
    value loop skips it — nothing in the old code ever asked 'does every RENDERED key exist
    in the payload?'. A fabricated row must not ship green."""
    p = _payload_with_assets()
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    # own-infra now carries its own rows (task 5c) — located by regex rather than a hand-typed
    # literal, since the exact rows markup (three "(unknown host)" rows, this fixture's
    # endpoints carry no `domain`) is tree.py's to own, not this test's to duplicate.
    m = re.search(r'<li data-node="own-infra"[^>]*>.*?</li>', html, re.S)
    assert m, "fixture drifted from the renderer's actual own-infra markup"
    own_infra_li = m.group(0)
    phantom = ('<li data-node="phantom" data-n="3" data-unit="rows">'
              '<span class="tc">3 phantom</span></li>')
    tampered = own_infra_li[:-len("</li>")] + f'<ul>{phantom}</ul></li>'
    html = html.replace(own_infra_li, tampered, 1)
    assert html != tree.html_tree(nodes)
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(html, p)
    assert e.value.check == "tree-node-set"


def _swap_li(html: str, key_a: str, key_b: str) -> str:
    """Swap two SIBLING leaf <li>...</li> blocks (no nested children of their own) by
    document position, leaving every attribute and every other byte untouched."""
    pat = lambda k: re.search(rf'<li data-node="{k}"[^>]*>.*?</li>', html, re.S)
    ma, mb = pat(key_a), pat(key_b)
    assert ma and mb, f"could not locate both {key_a!r} and {key_b!r} in the markup"
    assert ma.start() < mb.start(), "test assumes key_a renders before key_b"
    a, b = ma.group(0), mb.group(0)
    return html[:ma.start()] + b + html[ma.end():mb.start()] + a + html[mb.end():]


def test_reordering_two_sibling_nodes_is_a_violation():
    """Neither a sum check nor a per-key value check cares about ORDER — a dict lookup by key
    finds `tracked` and `queued` wherever they sit, and children summing to their parent does
    not depend on which one comes first. Swapping two siblings, individually correct values
    and all, is invisible to every check except one that compares the rendered SEQUENCE to
    the payload's own pre-order sequence."""
    p = _payload_with_assets()
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    swapped = _swap_li(html, "tracked", "queued")
    assert swapped != html
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(swapped, p)
    assert e.value.check == "tree-node-set"


def test_reordering_asset_hostclass_children_is_a_violation():
    """Same reorder class, one level deeper — two asset hostClass leaves swapped."""
    p = _payload_with_assets()
    nodes = tree.build(p)
    html = tree.html_tree(nodes)
    swapped = _swap_li(html, "boilerplate", "social-widget")
    assert swapped != html
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(swapped, p)
    assert e.value.check == "tree-node-set"


# ---------------------------------------------------------------------------------------
# Fix round 2 — smaller finding: `_tree_region` failed SILENTLY (returned "") when
# `<ul class="tree">` was not found, which disabled `_check_rendered_sums` with no complaint.
# ---------------------------------------------------------------------------------------

def test_missing_tree_wrapper_fails_loudly_not_silently():
    """Mangling only the tree's own wrapper (leaving every <li data-node=...> row intact, so
    the earlier 'no coverage tree found' guard does not fire — _tree_nodes scans the whole
    document, not just this wrapper) used to make `_tree_region` return "" and silently skip
    `_check_rendered_sums`. A missing/altered tree wrapper on a page that should have one must
    be a violation, not a quiet no-op."""
    p = _payload_with_assets()
    html = tree.html_tree(tree.build(p)).replace('<ul class="tree">', '<ul class="tree-x">', 1)
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_matches_payload(html, p)
    assert e.value.check == "tree-missing"


# ---------------------------------------------------------------------------------------
# Fix round 2 — smaller finding: `tree._li` crashed on a null/absent `hostClass` — the
# schema does not require the field. Reproduced end-to-end here (crash-level repro lives in
# test_tree.py); this proves the whole certified pipeline stays green for such a row too.
# ---------------------------------------------------------------------------------------

def test_null_hostclass_row_renders_and_verifies_cleanly():
    p = _payload_with_assets()
    p["endpoints"].append({"hostClass": None, "coverage": "na"})
    p["counts"]["coverage"]["na"] += 1
    p["counts"]["excluded"] += 1
    p["counts"]["detected"] += 1
    nodes = tree.build(p)                       # must not raise (AttributeError, pre-fix)
    html = tree.html_tree(nodes)                # must not raise
    md = "\n".join(tree.md_tree(nodes))
    verify.check_tree_matches_payload(html, p)
    verify.check_tree_parity(html, md)


# ---------------------------------------------------------------------------------------
# Fix round 2 — the false-RED sweep required by the brief: every one of these honest shapes
# must stay green after the node-set/order check, the _tree_region fix, and the null-hostClass
# fix. Re-run of the sweep the previous review already did, against the new code.
# ---------------------------------------------------------------------------------------

def test_false_red_sweep_honest_reports_stay_green():
    cases = {
        "childless assets (no endpoints)": _payload(),
        "empty payload": {},
    }
    p = _payload(); del p["counts"]["coverage"]
    cases["legacy payload, no coverage key"] = p
    cases["all-zero counts"] = {"counts": {
        "detected": 0, "integrations": 0, "excluded": 0, "apis": 0,
        "coverage": {"tracked": 0, "queued": 0, "needs-human": 0, "blocked": 0, "na": 0}}}
    cases["all-null counts"] = {"counts": {
        "detected": None, "integrations": None, "excluded": None, "coverage": None}}
    def _plus_one_na(p, hc):
        p["endpoints"].append({"hostClass": hc, "coverage": "na"})
        p["counts"]["coverage"]["na"] += 1
        p["counts"]["excluded"] += 1
        p["counts"]["detected"] += 1
        return p

    cases["'&'/'<' in a hostClass label"] = _plus_one_na(_payload_with_assets(), "weird&<class>")
    cases["unknown hostClass"] = _plus_one_na(_payload_with_assets(), "mystery-class")

    for name, payload in cases.items():
        nodes = tree.build(payload)
        html = tree.html_tree(nodes)
        md = "\n".join(tree.md_tree(nodes))
        try:
            verify.check_tree_matches_payload(html, payload)
            verify.check_tree_parity(html, md)
        except verify.Violation as v:
            pytest.fail(f"false RED on {name!r}: [{v.check}] {v.detail}")

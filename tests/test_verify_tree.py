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
    trimmed = re.sub(r'<li data-node="own-infra"[^>]*><span class="tc">[^<]*</span></li>',
                     "", html, count=1)
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
        html, n = re.subn(rf'<li data-node="{hc}"[^>]*><span class="tc">[^<]*</span></li>',
                          "", html, count=1)
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

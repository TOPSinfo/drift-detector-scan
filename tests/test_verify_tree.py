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

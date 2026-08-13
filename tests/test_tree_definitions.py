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


def test_unmapped_hostclass_does_not_false_red():
    """A future classifier can emit a hostClass nobody has written a definition for —
    `_ASSET_CLASSES` is an ordering preference, not a filter (see tree.py's own comment),
    so `build()` still emits a child node for it. That must never turn an honest scan red:
    `html_definitions` emits a `data-def` for every rendered key regardless of whether
    `DEFINITIONS` has prose for it, so the RUNTIME pairing check stays green. Completeness of
    the English text is enforced separately, at dev time, by
    `test_every_node_has_a_definition` above — never by the thing that gates a real repo's
    scan."""
    payload = {"counts": {"detected": 5, "integrations": 0, "excluded": 5,
                          "coverage": {"tracked": 0, "queued": 0, "needs-human": 0,
                                       "blocked": 0, "na": 5},
                          "hostClasses": {}},
              "endpoints": [{"hostClass": "some-future-class", "coverage": "na"}] * 5}
    nodes = tree.build(payload)
    html = tree.html_tree(nodes) + tree.html_definitions(nodes)
    # no KeyError, no exception — and verify agrees it's clean
    verify.check_tree_definitions(html)

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


def _payload_with_unmapped_class():
    """The reviewer's repro: 3 `na` rows whose hostClass is not in `_ASSET_CLASSES`.

    A filter (iterate the fixed tuple, look up each) drops these 3 rows from the children
    while `assets.n` still counts them via `cov["na"]` — a silent 3-row discrepancy in the
    one structure whose entire job is to sum correctly."""
    p = _payload()
    p["endpoints"] += [{"domain": f"h{i}.mystery-class.test", "hostClass": "mystery-class",
                        "coverage": "na"} for i in range(3)]
    p["counts"]["coverage"]["na"] += 3
    p["counts"]["excluded"] += 3
    p["counts"]["detected"] += 3
    return p


def test_unmapped_hostclass_is_not_dropped_from_the_sum():
    """Reviewer repro: an unmapped hostClass must still appear as a child, so assets.n stays
    equal to the sum of its children rather than silently drifting ahead of them."""
    f = _flat(tree.build(_payload_with_unmapped_class()))
    assert f["assets"]["n"] == 46
    kids = {c["key"]: c["n"] for c in f["assets"]["children"]}
    assert "mystery-class" in kids
    assert kids["mystery-class"] == 3
    assert sum(kids.values()) == f["assets"]["n"]


def test_unmapped_hostclass_ordering_is_deterministic():
    """Known classes render first, in `_ASSET_CLASSES` order; unknown ones follow, alphabetical
    — never sorted by count. Two runs of the same payload must render identically."""
    p = _payload_with_unmapped_class()
    b1, b2 = tree.build(p), tree.build(p)
    assert b1 == b2

    f = _flat(b1)
    keys = [c["key"] for c in f["assets"]["children"]]
    known = [k for k in tree._ASSET_CLASSES if k in keys]
    unknown = sorted(k for k in keys if k not in tree._ASSET_CLASSES)
    assert keys == known + unknown
    assert "mystery-class" in unknown


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
    assert "20 boilerplate" in body               # count-then-label, per the tree's own shape
    # box-drawing, so it reads as a tree in a terminal and on GitHub
    assert "├─" in body and "└─" in body


def test_md_tree_states_a_null_count_rather_than_printing_zero():
    p = _payload()
    del p["counts"]["coverage"]
    body = "\n".join(tree.md_tree(tree.build(p)))
    assert "not counted" in body
    assert "0 integrations" not in body


def test_null_node_with_no_note_still_shows_its_label():
    """A null count with no note is not hypothetical — real callers always attach a note today,
    but the whole point of a null count is to say WHAT is not counted. An unnoted null leaf must
    never render as a bare, unidentifiable 'not counted'."""
    node = tree._node("integrations", None)
    body = "\n".join(tree.md_tree([node]))
    assert "not counted" in body
    assert "integrations" in body


def test_endpoint_with_null_hostclass_does_not_crash_the_renderer():
    """The schema does not REQUIRE `hostClass` — a real endpoint row can carry
    `hostClass: null`, or omit the field entirely (`.get` returns None either way). Before
    the fix, that None became a node `key`, and `_li` calls `html.escape(node["key"])` —
    `html.escape(None)` raises AttributeError, crashing the whole render instead of showing
    an honest 'we don't know its class' row."""
    p = _payload()
    p["endpoints"] += [{"domain": "h0.mystery.test", "hostClass": None, "coverage": "na"}]
    p["counts"]["coverage"]["na"] += 1
    p["counts"]["excluded"] += 1
    p["counts"]["detected"] += 1

    nodes = tree.build(p)                 # must not raise
    html = tree.html_tree(nodes)          # must not raise (the AttributeError site)
    body = "\n".join(tree.md_tree(nodes))  # must not raise

    f = _flat(nodes)
    kids = {c["key"]: c["n"] for c in f["assets"]["children"]}
    assert sum(kids.values()) == f["assets"]["n"]     # the null row is still counted, not lost
    assert None not in kids                            # never a raw None key
    assert "None" not in html and "None" not in body    # an honest label, not Python's str(None)


def test_md_tree_includes_the_roots_own_note():
    """`_li` (the HTML renderer) always emits a node's `.tnote` span, root included; `md_tree`
    only ever calls `_fmt(root)`, which has no note wording at all — the root's own note is
    silently dropped in the Markdown while it would render in the HTML. Harmless today because
    no root ever carries a note, but the day one does this is a latent false RED in
    `check_tree_parity`: the HTML root's text would carry the note and the ASCII root line
    would not, so they would never match even though nothing about the DATA disagrees. The two
    renderers must agree on every node, root included."""
    root = tree._node("detected", 73, note="a root note")
    md_line = tree.md_tree([root])[0]
    assert "a root note" in md_line

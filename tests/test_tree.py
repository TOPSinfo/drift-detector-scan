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


# ---------------------------------------------------------------------------------------
# Task 5d — the tree splits by repo. Origin: the first multi-repo scan (mls-mapper +
# promoteplus-crm + sebago-foods, 142 endpoints) melted three repos into one set of numbers;
# the owner called that out as "one confusion point is repo mixing". Repo becomes level 1 —
# but ONLY when the scan covered more than one repo, so a single-repo tree still renders
# exactly what it renders today.
# ---------------------------------------------------------------------------------------

def _multi_repo_payload():
    """A small stand-in for the real three-repo scan (8/73/61 = 142), shaped the same way:
    each repo gets its own tracked/queued/na rows, scaled down so the sums are checkable by
    eye. `sebago-foods` has the most endpoints but must still render LAST — alphabetical
    order, never by count."""
    def eps(repo, n_tracked, n_queued, n_na):
        out = []
        for i in range(n_tracked):
            out.append({"repo": repo, "domain": f"api{i}.{repo}.test", "hostClass": "api",
                        "coverage": "tracked", "vendor": f"{repo}-vendor{i}", "version": "v1"})
        for i in range(n_queued):
            out.append({"repo": repo, "domain": f"q{i}.{repo}.test", "hostClass": "unclassified",
                        "coverage": "queued"})
        for i in range(n_na):
            out.append({"repo": repo, "domain": f"a{i}.{repo}.test", "hostClass": "boilerplate",
                        "coverage": "na"})
        return out

    endpoints = (eps("mls-mapper", 3, 0, 5)
                + eps("promoteplus-crm", 27, 3, 43)
                + eps("sebago-foods", 20, 1, 40))
    return {"counts": {"detected": len(endpoints)}, "endpoints": endpoints}


def test_repo_level_appears_only_when_more_than_one_repo():
    nodes = tree.build(_multi_repo_payload())
    root = nodes[0]
    kids = root["children"]
    assert {c["key"] for c in kids} == {"repo"}          # data-node is the SEMANTIC key "repo"
    assert [c["label"] for c in kids] == ["mls-mapper", "promoteplus-crm", "sebago-foods"]


def test_single_repo_payload_has_no_repo_level():
    """The exact SAME shape `_payload()` already exercises everywhere else in this file — a
    single repo's rows carry no `repo` field variety at all, so the tree must render exactly
    as it does in every other test in this module: integrations/assets, no repo wrapper."""
    nodes = tree.build(_payload())
    kids = {c["key"] for c in nodes[0]["children"]}
    assert kids == {"integrations", "assets"}


def test_endpoints_with_no_repo_field_render_no_repo_level():
    """False-red sweep case: a payload whose endpoints simply never carry a `repo` field must
    not spontaneously grow a repo level — there is nothing to disambiguate."""
    nodes = tree.build(_payload())               # _eps() rows never set "repo" at all
    kids = {c["key"] for c in nodes[0]["children"]}
    assert kids == {"integrations", "assets"}


def test_each_repo_subtree_sums_to_its_own_total_and_repos_sum_to_root():
    nodes = tree.build(_multi_repo_payload())
    root = nodes[0]
    total = 0
    for repo_node in root["children"]:
        kids_sum = sum(c["n"] for c in repo_node["children"])
        assert kids_sum == repo_node["n"], repo_node["label"]
        total += repo_node["n"]
    assert total == root["n"] == 8 + 73 + 61 == 142


def test_repo_node_carries_data_repo_and_a_unique_data_path():
    html = tree.html_tree(tree.build(_multi_repo_payload()))
    assert 'data-repo="mls-mapper"' in html
    assert 'data-path="detected/mls-mapper"' in html
    assert 'data-path="detected/mls-mapper/integrations/tracked"' in html
    assert 'data-path="detected/promoteplus-crm/integrations/tracked"' in html
    # the SAME semantic data-node repeats once per repo — that is the whole point of
    # separating identity (data-path) from the glossary key (data-node).
    assert html.count('data-node="tracked"') == 3


def test_single_repo_paths_match_todays_implicit_shape():
    """`data-path` is a NEW attribute added everywhere, single-repo included — but the shape it
    encodes for a single-repo tree is exactly today's implicit nesting, and no `data-repo`
    attribute appears anywhere on a single-repo page."""
    html = tree.html_tree(tree.build(_payload()))
    assert 'data-path="detected"' in html
    assert 'data-path="detected/integrations"' in html
    assert 'data-path="detected/integrations/tracked"' in html
    assert 'data-path="detected/assets/boilerplate"' in html
    assert "data-repo=" not in html


def test_repos_render_in_a_fixed_alphabetical_order_never_by_count():
    """sebago-foods (61) outnumbers mls-mapper (8) — order must stay alphabetical, not
    largest/smallest first."""
    html = tree.html_tree(tree.build(_multi_repo_payload()))
    assert (html.index('data-repo="mls-mapper"') < html.index('data-repo="promoteplus-crm"')
           < html.index('data-repo="sebago-foods"'))


def test_a_repo_with_zero_integrations_still_sums():
    p = _multi_repo_payload()
    p["endpoints"] = [e for e in p["endpoints"]
                      if not (e["repo"] == "mls-mapper" and e["coverage"] != "na")]
    p["counts"]["detected"] = len(p["endpoints"])
    nodes = tree.build(p)
    mls = next(c for c in nodes[0]["children"] if c["label"] == "mls-mapper")
    integ = next(c for c in mls["children"] if c["key"] == "integrations")
    assert integ["n"] == 0
    assert sum(c["n"] for c in mls["children"]) == mls["n"]


def test_md_tree_renders_the_repo_level():
    body = "\n".join(tree.md_tree(tree.build(_multi_repo_payload())))
    assert "8 mls-mapper" in body
    assert "73 promoteplus-crm" in body
    assert "61 sebago-foods" in body


def test_repo_is_defined_in_the_glossary():
    assert "repo" in tree.DEFINITIONS


def test_build_is_pure_and_deterministic_across_repos():
    p = _multi_repo_payload()
    assert tree.build(p) == tree.build(p)


def test_false_red_sweep_for_the_repo_split():
    """Task 5d requirement 6: none of these honest shapes may gain a spurious repo level,
    crash, or fail to sum at any depth."""
    cases = {}
    cases["single-repo payload"] = _payload()
    p = _payload(); del p["endpoints"]
    cases["no endpoints"] = p
    cases["empty payload"] = {}
    p = _multi_repo_payload()
    p["endpoints"] = [e for e in p["endpoints"]
                      if not (e["repo"] == "mls-mapper" and e["coverage"] != "na")]
    p["counts"]["detected"] = len(p["endpoints"])
    cases["a repo with zero integrations"] = p
    cases["multi-repo payload"] = _multi_repo_payload()

    def _sums_ok(nodes, label):
        for n in nodes:
            if n["children"]:
                kids = [c["n"] for c in n["children"]]
                if n["n"] is not None and all(k is not None for k in kids):
                    assert sum(kids) == n["n"], f"{label}: {n['key']} sum mismatch"
            _sums_ok(n["children"], label)

    for name, payload in cases.items():
        nodes = tree.build(payload)               # must not raise
        tree.html_tree(nodes)                      # must not raise
        "\n".join(tree.md_tree(nodes))              # must not raise
        _sums_ok(nodes, name)

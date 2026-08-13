"""summary.html is the report's DEFAULT view: the coverage tree + its glossary + the headline
numbers (fixes/sunsets/past-due/unaudited), with zero JavaScript. The cockpit (dashboard.html)
is a Vue application; reading twelve numbers should not require loading one — see
`agent/lib/tree.py`'s own contract for why the tree itself must not need a framework to be
correct, and `docs/superpowers/plans/2026-08-13-dashboard-reframe.md`'s "Task 5b" for why this
page exists at all (Stage 1 landed the tree at the BOTTOM of the cockpit, under the tile strip
it was meant to replace — a placement bug, not a design choice).

The verify checks that used to police dashboard.html's tree (tree-sums, tree-payload,
tree-units, tree-parity, tree-node-set, tree-definitions, tree-missing, tree-text-mismatch) now
police THIS page instead — see `agent/cli.py`'s verify command. This file proves the page
carries what those checks parse, and that dashboard.html no longer duplicates the tree.
"""
import re

from agent.lib.dashboard_render import render_payload
from agent.lib.summary_render import render_summary


def _eps():
    """Endpoint rows mirroring a real scan (same shape as tests/test_tree.py's fixture) — the
    asset breakdown is derived from these, not from counts.hostClasses."""
    def rows(n, hc, cov):
        return [{"domain": f"h{i}.{hc}.test", "hostClass": hc, "coverage": cov} for i in range(n)]
    return (rows(27, "api", "tracked")
            + rows(3, "unclassified", "queued")
            + rows(20, "boilerplate", "na") + rows(12, "social-widget", "na")
            + rows(5, "vendored-lib", "na") + rows(3, "asset-cdn", "na")
            + rows(3, "own-infra", "na"))


def _payload():
    # mirrors a real scan: 73 detected = 30 integrations + 43 assets; 30 = 27 tracked + 3 queued
    return {"counts": {"detected": 73, "integrations": 30, "excluded": 43, "unknown": 3,
                       "apis": 21, "fixes": 4, "sunsets": 2, "pastDue": 1, "unaudited": 5,
                       "reposScanned": 3,
                       "coverage": {"tracked": 27, "queued": 3, "needs-human": 0,
                                    "blocked": 0, "na": 43}},
            "generated": "2026-08-13", "endpoints": _eps(), "catalog": [], "actions": [],
            "coverageGrades": [], "notes": []}


def test_the_tree_and_its_data_nodes_are_on_the_page():
    page = render_summary(_payload(), "2026-08-13")
    assert '<ul class="tree"' in page
    assert 'data-node="detected"' in page


def test_no_javascript_whatsoever():
    """Not Vue, not a snippet — if it needed JS to be correct it would not be a projection."""
    page = render_summary(_payload(), "2026-08-13")
    for banned in ("<script", "onclick", "{{", "v-for", "v-if", "@click"):
        assert banned not in page, banned


def test_the_glossary_is_present():
    page = render_summary(_payload(), "2026-08-13")
    for key in ("detected", "integrations", "tracked", "queued", "assets"):
        assert f'data-def="{key}"' in page


def test_deterministic_same_payload_same_bytes():
    p = _payload()
    assert render_summary(p, "2026-08-13") == render_summary(p, "2026-08-13")


def test_a_hostile_hostclass_is_escaped():
    """A hostClass value is attacker-influenceable (it derives from a scanned repo's own
    strings). It must come out escaped both as text and as the data-node attribute."""
    p = _payload()
    p["endpoints"] = [{"domain": "h0.evil.test", "hostClass": "<script>x</script>",
                       "coverage": "na"}]
    p["counts"]["coverage"] = {"tracked": 0, "queued": 0, "needs-human": 0, "blocked": 0, "na": 1}
    p["counts"]["detected"] = 1
    p["counts"]["integrations"] = 0
    p["counts"]["excluded"] = 1
    page = render_summary(p, "2026-08-13")
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;x&lt;/script&gt;" in page


def test_headline_numbers_are_read_from_the_real_counts_keys():
    """fixes/sunsets/pastDue/unaudited — the real key names in payload['counts'], not
    guessed/renamed ones."""
    page = render_summary(_payload(), "2026-08-13")
    assert re.search(r"<dd>4</dd>", page)   # fixes
    assert re.search(r"<dd>2</dd>", page)   # sunsets
    assert re.search(r"<dd>1</dd>", page)   # pastDue
    assert re.search(r"<dd>5</dd>", page)   # unaudited


def test_meta_line_carries_repo_count_and_generated_date():
    page = render_summary(_payload(), "2026-08-13")
    assert "3" in page.split('<div id="tree">')[0]     # reposScanned
    assert "2026-08-13" in page.split('<div id="tree">')[0]   # generated


def test_dashboard_no_longer_carries_the_tree():
    """The tree moved OUT of the cockpit entirely — one tree per surface, not a duplicate."""
    page = render_payload(_payload(), "2026-08-13")
    assert 'id="coverage-tree"' not in page
    assert '<ul class="tree"' not in page

"""The tree is a PROJECTION of drift.json rendered as structured HTML markup, not a widget.

`html_tree` mirrors `md_tree`: same nodes, same wording for a null count ("not counted
(label)"), different surface. A <pre> could only be grepped; a <ul> with data-node/data-n/
data-unit attributes can be PARSED and its arithmetic checked by `verify` — that's the whole
point of rendering it server-side.
"""
import re

from agent.lib import tree
from agent.lib.dashboard_render import render_payload


def _eps():
    """Endpoint rows mirroring a real scan (same shape as tests/test_tree.py's fixture) — the
    asset breakdown is derived from these, not from counts.hostClasses, so the fixture must
    carry them or the assets node renders childless."""
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
                       "apis": 21,
                       "coverage": {"tracked": 27, "queued": 3, "needs-human": 0,
                                    "blocked": 0, "na": 43}},
            "generated": "2026-08-13", "endpoints": _eps(), "catalog": [], "actions": [],
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


def test_null_count_wording_matches_md_tree():
    """Carried from the last review: md_tree renders a null count as `not counted (label)`.
    html_tree must use the same wording so the two projections read the same."""
    p = _payload()
    del p["counts"]["coverage"]
    md_body = "\n".join(tree.md_tree(tree.build(p)))
    html = tree.html_tree(tree.build(p))
    assert "not counted (integrations)" in md_body
    assert "not counted (integrations)" in html


def test_the_tree_needs_no_javascript():
    """It must be readable with JS disabled — if it needs a framework to be correct, it is not
    a projection. No Vue bindings, no event handlers in the emitted fragment."""
    html = tree.html_tree(tree.build(_payload()))
    for banned in ("v-for", "v-if", "{{", "@click", "onclick"):
        assert banned not in html, banned


def test_the_tree_is_no_longer_embedded_in_the_dashboard():
    """Task 5b moved the tree OUT of the cockpit onto its own page (summary.html — see
    agent/lib/summary_render.py and tests/test_summary_page.py). Stage 1 had injected it here,
    at the BOTTOM of this Vue application, under the very tile strip it was meant to replace —
    a placement bug the owner asked to fix by giving the tree its own bare-bones page instead."""
    html = render_payload(_payload(), "2026-08-13")
    assert '<ul class="tree"' not in html
    assert 'id="coverage-tree"' not in html


def test_html_is_escaped():
    """A hostClass value is attacker-influenceable (it derives from a scanned repo's own
    strings). It must come out escaped both as text and as the data-node attribute — the
    asset breakdown is the one place a raw, non-closed-vocabulary string reaches the tree."""
    p = _payload()
    p["endpoints"] = [{"domain": "h0.evil.test", "hostClass": "<script>x</script>",
                       "coverage": "na"}]
    p["counts"]["coverage"] = {"tracked": 0, "queued": 0, "needs-human": 0, "blocked": 0,
                               "na": 1}
    p["counts"]["detected"] = 1
    p["counts"]["integrations"] = 0
    p["counts"]["excluded"] = 1
    html = tree.html_tree(tree.build(p))
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html

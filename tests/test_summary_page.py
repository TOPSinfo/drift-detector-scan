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

import pytest

from agent.lib import verify
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
    for key in ("detected", "integrations", "tracked", "unresolved", "assets"):
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
    guessed/renamed ones. Each tile also carries a `data-count` binding (task-5b Finding 1)
    so the value the reader sees is machine-checkable, not just plausible-looking."""
    page = render_summary(_payload(), "2026-08-13")
    assert re.search(r'<dd data-count="fixes">4</dd>', page)
    assert re.search(r'<dd data-count="sunsets">2</dd>', page)
    assert re.search(r'<dd data-count="pastDue">1</dd>', page)
    assert re.search(r'<dd data-count="unaudited">5</dd>', page)


def test_meta_line_carries_repo_count_and_generated_date():
    page = render_summary(_payload(), "2026-08-13")
    assert "3" in page.split('<div id="tree">')[0]     # reposScanned
    assert "2026-08-13" in page.split('<div id="tree">')[0]   # generated


def test_dashboard_no_longer_carries_the_tree():
    """The tree moved OUT of the cockpit entirely — one tree per surface, not a duplicate."""
    page = render_payload(_payload(), "2026-08-13")
    assert 'id="coverage-tree"' not in page
    assert '<ul class="tree"' not in page


# ---------------------------------------------------------------------------------------
# Fix round 1, Finding 1 — the headline tiles carried no machine-readable binding to
# payload["counts"], so `verify` never noticed a hand-tampered digit. Reproduce the exact
# bugs the review flagged (a tampered <dd>, a tampered repo count), then require
# `verify.check_summary_headline` to catch them.
# ---------------------------------------------------------------------------------------

def test_a_faithful_summary_page_passes_the_headline_check():
    page = render_summary(_payload(), "2026-08-13")
    verify.check_summary_headline(page, _payload())   # no raise


def test_tampering_the_unaudited_tile_is_caught():
    """Verified bug: hand-editing <dd>5</dd> -> <dd>0</dd> for Unaudited used to leave
    `verify` green."""
    page = render_summary(_payload(), "2026-08-13")
    tampered = page.replace('<dd data-count="unaudited">5</dd>', '<dd data-count="unaudited">0</dd>')
    assert tampered != page
    with pytest.raises(verify.Violation) as e:
        verify.check_summary_headline(tampered, _payload())
    assert e.value.check == "summary-headline"


def test_tampering_the_repo_count_is_caught():
    """Verified bug: '1 repo(s)' -> '99 repo(s)' used to leave `verify` green."""
    page = render_summary(_payload(), "2026-08-13")
    tampered = page.replace('<span data-count="reposScanned">3</span>',
                            '<span data-count="reposScanned">99</span>')
    assert tampered != page
    with pytest.raises(verify.Violation) as e:
        verify.check_summary_headline(tampered, _payload())
    assert e.value.check == "summary-headline"


def test_false_red_sweep_headline_check_stays_green_on_honest_shapes():
    """The check must never fire on an honest report, including payload shapes that legally
    lack a counts key (a legacy payload, an empty payload) — an absent count is 'not counted',
    not a violation. Mirrors the sweep in test_verify_tree.py for the tree checks."""
    cases = {}
    cases["full payload"] = _payload()
    p = _payload(); del p["counts"]["unaudited"]
    cases["legacy payload, missing 'unaudited' key"] = p
    cases["empty payload"] = {}
    p = _payload(); p["counts"] = {**p["counts"], "fixes": 0, "sunsets": 0, "pastDue": 0,
                                   "unaudited": 0, "reposScanned": 0}
    cases["all-zero counts"] = p
    p = _payload(); p["counts"] = {**p["counts"], "fixes": None, "sunsets": None,
                                   "pastDue": None, "unaudited": None, "reposScanned": None}
    cases["null-count headline"] = p
    p = _payload_with_unmapped_hostclass()
    cases["unmapped hostClass"] = p

    for name, payload in cases.items():
        page = render_summary(payload, "2026-08-13")
        try:
            verify.check_summary_headline(page, payload)
        except verify.Violation as v:
            pytest.fail(f"false RED on {name!r}: [{v.check}] {v.detail}")


def _payload_with_unmapped_hostclass():
    p = _payload()
    p["endpoints"] = p["endpoints"] + [{"domain": "h99.mystery.test", "hostClass": "mystery-class",
                                        "coverage": "na"}]
    p["counts"] = {**p["counts"], "excluded": p["counts"]["excluded"] + 1,
                   "detected": p["counts"]["detected"] + 1}
    return p

"""tree.py's leaf nodes used to claim a bare count — "20 boilerplate" — that nobody could check
without re-running the scan. Task 5c makes each leaf carry the actual rows (hosts, and each
host's file:line locations) so the claim is self-evidencing: `verify.check_tree_rows` proves the
rendered rows are exactly the payload's own endpoints for that node's bucket — never fewer (a
dropped row) and never more (an invented one) — and that a truncated `files[]` says so rather
than rendering a partial list as if it were complete.
"""
import re

import pytest

from agent.lib import tree, verify


def _eps():
    """Endpoint rows exercising every row-rendering path: two ordinary tracked rows (one
    CURRENT, one UNAUDITED — the honesty signal that must be visible), a queued row carrying
    an ownInfraReason, a boilerplate (na) row, and a tracked row whose files[] is TRUNCATED
    (file_count=45, only 20 locations carried) — the reference-repo shape task 5c calls out
    by name (www.googleapis.com: 45 call-sites, 20 locations)."""
    return [
        # deliberately no files/file_count — the "delete this row" target has to be a single,
        # self-contained <div> with no nested location markup so removing it is unambiguous.
        {"domain": "api0.vendor0.test", "hostClass": "api", "coverage": "tracked",
         "vendor": "vendor0", "version": "v1"},
        {"domain": "api1.vendor1.test", "hostClass": "api", "coverage": "tracked",
         "vendor": "vendor1", "version": "v2", "file_count": 2,
         "files": ["src/a1.py:1", "src/a1.py:2"]},
        {"domain": "big.vendor.test", "hostClass": "api", "coverage": "tracked",
         "vendor": "bigvendor", "version": "v9", "file_count": 45,
         "files": [f"src/big.py:{n}" for n in range(20)]},
        {"domain": "queued.example.test", "hostClass": "unclassified", "coverage": "queued",
         "ownInfraReason": "repo token 'example'", "file_count": 1, "files": ["src/q.py:1"]},
        {"domain": "b0.schema.test", "hostClass": "boilerplate", "coverage": "na",
         "file_count": 1, "files": ["schema.json:1"]},
    ]


def _payload():
    eps = _eps()
    return {"counts": {"detected": len(eps), "integrations": 4, "excluded": 1, "apis": 3,
                       "coverage": {"tracked": 3, "queued": 1, "needs-human": 0,
                                    "blocked": 0, "na": 1}},
            "endpoints": eps,
            "catalog": [{"vendor": "vendor0", "verdict": "CURRENT"},
                        {"vendor": "vendor1", "verdict": "UNAUDITED"},
                        {"vendor": "bigvendor", "verdict": "STALE"}]}


def _render():
    return tree.html_tree(tree.build(_payload()))


# ---------------------------------------------------------------------------------------
# Rendering shape
# ---------------------------------------------------------------------------------------

def test_rows_render_but_never_carry_data_node():
    """Requirement 1: a row is not a tree node. If a row's element carried `data-node`,
    `verify._tree_nodes` would count it as a coverage-tree node and both tree-parity and
    tree-node-set — hard-won invariants that already closed real false greens — would break."""
    html = _render()
    assert 'data-row="api0.vendor0.test"' in html
    for row_div in re.findall(r'<div class="row"[^>]*>', html):
        assert "data-node=" not in row_div


def test_a_tracked_row_shows_vendor_version_and_catalog_verdict():
    """An UNAUDITED verdict is the honesty surface this whole tool exists to make visible —
    it must render on the row, not just live silently in payload['catalog']."""
    html = _render()
    assert "vendor1" in html and "UNAUDITED" in html
    assert "vendor0" in html and "CURRENT" in html


def test_a_queued_row_shows_its_own_infra_reason():
    import html as _html
    html = _render()
    assert "repo token" in html and "example" in _html.unescape(html)


def test_truncated_files_are_disclosed_not_silently_shortened():
    """Requirement 5, measured on the reference repo: 16 of 73 endpoints carry fewer
    locations than their file_count. Rendering the short list unqualified would claim
    completeness while hiding the rest — 'cannot see' presented as 'clean'."""
    html = _render()
    assert "showing 20 of 45" in html


def test_an_untruncated_row_carries_no_showing_of_text():
    html = _render()
    # api1 has file_count == len(files) == 2 — nothing was hidden, so no disclosure is owed.
    i = html.index("a1.py:1")
    assert "showing 2 of 2" not in html[max(0, i - 300):i + 300]


def test_no_javascript_in_the_row_markup():
    html = _render()
    for banned in ("<script", "onclick", "{{", "v-for", "@click"):
        assert banned not in html, banned


def test_md_tree_carries_no_rows():
    """Requirement 3: rows are HTML-only. 176 file locations do not belong in drift.md —
    the ASCII tree stays counts-only."""
    body = "\n".join(tree.md_tree(tree.build(_payload())))
    assert "api0.vendor0.test" not in body
    assert "src/a1.py:1" not in body
    assert "showing 20 of 45" not in body


def test_deterministic_same_payload_same_bytes():
    p = _payload()
    assert tree.html_tree(tree.build(p)) == tree.html_tree(tree.build(p))


# ---------------------------------------------------------------------------------------
# verify.check_tree_rows — the three failure classes, plus a faithful pass
# ---------------------------------------------------------------------------------------

def test_a_faithful_render_passes():
    verify.check_tree_rows(_render(), _payload())   # no raise


def test_a_deleted_row_is_a_violation():
    """A row silently dropped — the tree undercounts what the scan actually found."""
    html = _render()
    # api0's row carries no nested <div> (no files), so it is a single, self-contained
    # element and can be removed with a plain non-greedy match with no risk of eating a
    # sibling row's markup.
    stripped = re.sub(r'<div class="row" data-row="api0\.vendor0\.test">.*?</div>', "",
                      html, count=1)
    assert stripped != html
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_rows(stripped, _payload())
    assert e.value.check == "tree-rows"


def test_an_added_row_is_a_violation():
    """A row fabricated out of thin air — the tree overcounts, claiming a call-site nobody
    scanned. Duplicating a real row still overcounts: the rendered count must equal data-n
    exactly, not merely be a subset of real hosts."""
    html = _render()
    dup = re.search(r'<div class="row" data-row="api0\.vendor0\.test">.*?</div>', html).group(0)
    inflated = html.replace(dup, dup + dup, 1)
    assert inflated != html
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_rows(inflated, _payload())
    assert e.value.check == "tree-rows"


def test_a_renamed_host_is_a_violation():
    """The count can stay honest while the CONTENT lies — a host swapped for one that never
    appeared in drift.json. This is the check's other half: existence, not just arithmetic."""
    html = _render()
    tampered = html.replace('data-row="api0.vendor0.test"', 'data-row="not-a-real-host.test"', 1)
    assert tampered != html
    with pytest.raises(verify.Violation) as e:
        verify.check_tree_rows(tampered, _payload())
    assert e.value.check == "tree-rows"


# ---------------------------------------------------------------------------------------
# No false REDs — an honest report must stay green on every edge shape.
# ---------------------------------------------------------------------------------------

def test_version_renders_verbatim_without_adding_prefix():
    """The version field already carries its prefix (v1, 2024-01, 3.0).
    Rendering must not prepend another v — output shows the payload verbatim.
    This is the fix for the 'vv1' bug on Anthropic, DeepSeek, Groq rows."""
    payload = {"counts": {"detected": 4, "integrations": 4, "excluded": 0, "apis": 4,
                          "coverage": {"tracked": 4, "queued": 0, "needs-human": 0,
                                       "blocked": 0, "na": 0}},
               "endpoints": [
                   {"domain": "api1.test", "hostClass": "api", "coverage": "tracked",
                    "vendor": "Anthropic", "version": "v1"},
                   {"domain": "api2.test", "hostClass": "api", "coverage": "tracked",
                    "vendor": "Shopify", "version": "2024-01"},
                   {"domain": "api3.test", "hostClass": "api", "coverage": "tracked",
                    "vendor": "Custom", "version": "3.0"},
                   {"domain": "api4.test", "hostClass": "api", "coverage": "tracked",
                    "vendor": "NoVersion", "version": None},
               ],
               "catalog": [{"vendor": "Anthropic", "verdict": "CURRENT"},
                          {"vendor": "Shopify", "verdict": "CURRENT"},
                          {"vendor": "Custom", "verdict": "CURRENT"},
                          {"vendor": "NoVersion", "verdict": "CURRENT"}]}
    html = tree.html_tree(tree.build(payload))

    # Version prefixes already in payload must render verbatim
    assert 'v1</span>' in html, "v1 should render as v1, not vv1"
    assert 'vv1</span>' not in html, "should not double the v prefix"
    assert '2024-01</span>' in html, "calendar version should render unchanged"
    assert '3.0</span>' in html, "numeric version should render unchanged"

    # The NoVersion row should have no version span at all (or span with no version text)
    # Extract the NoVersion row to check it has no stray version separator
    import re
    noversion_rows = re.findall(r'<div class="row" data-row="api4\.test">.*?</div>', html, re.DOTALL)
    assert len(noversion_rows) == 1
    noversion_row = noversion_rows[0]
    # Should have "NoVersion" vendor but no version text after it
    assert "NoVersion" in noversion_row
    # Check there's no span with empty or stray content between vendor and verdict
    assert 'class="rvendor">NoVersion</span>' in noversion_row


def test_false_red_sweep_stays_green_on_honest_shapes():
    cases = {}
    cases["full payload"] = _payload()

    p = _payload(); del p["endpoints"]
    cases["no endpoints key at all"] = p

    cases["empty payload"] = {}

    p = _payload(); del p["counts"]["coverage"]
    cases["payload with no coverage"] = p

    p = _payload()
    p["counts"] = {**p["counts"], "coverage": {"tracked": 0, "queued": 0, "needs-human": 0,
                                               "blocked": 0, "na": 0},
                   "detected": 0, "integrations": 0, "excluded": 0}
    p["endpoints"] = []
    cases["all-zero counts, endpoints present but empty"] = p

    p = _payload()
    node_integrations_null = p  # coverage present, detected null downstream via missing key
    del p["counts"]["detected"]
    cases["a null-count node (detected)"] = node_integrations_null

    p = _payload()
    p["endpoints"] = p["endpoints"] + [{"domain": "h9.mystery.test", "hostClass": "mystery-class",
                                        "coverage": "na"}]
    p["counts"] = {**p["counts"], "coverage": {**p["counts"]["coverage"],
                                               "na": p["counts"]["coverage"]["na"] + 1},
                   "excluded": p["counts"]["excluded"] + 1,
                   "detected": p["counts"]["detected"] + 1}
    cases["unmapped hostClass"] = p

    p = _payload()
    p["endpoints"] = p["endpoints"] + [{"domain": "empty-files.test", "hostClass": "api",
                                        "coverage": "tracked", "vendor": "vendor0",
                                        "version": "v1", "files": []}]
    p["counts"] = {**p["counts"], "coverage": {**p["counts"]["coverage"],
                                               "tracked": p["counts"]["coverage"]["tracked"] + 1},
                   "integrations": p["counts"]["integrations"] + 1,
                   "detected": p["counts"]["detected"] + 1}
    cases["endpoint with an empty files list"] = p

    p = _payload()
    p["endpoints"] = p["endpoints"] + [{"domain": "no-files-key.test", "hostClass": "api",
                                        "coverage": "tracked", "vendor": "vendor0",
                                        "version": "v1"}]
    p["counts"] = {**p["counts"], "coverage": {**p["counts"]["coverage"],
                                               "tracked": p["counts"]["coverage"]["tracked"] + 1},
                   "integrations": p["counts"]["integrations"] + 1,
                   "detected": p["counts"]["detected"] + 1}
    cases["endpoint with a missing files key"] = p

    for name, payload in cases.items():
        html = tree.html_tree(tree.build(payload))
        try:
            verify.check_tree_rows(html, payload)
        except verify.Violation as v:
            pytest.fail(f"false RED on {name!r}: [{v.check}] {v.detail}")

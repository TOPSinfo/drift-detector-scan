"""The cockpit must not promise work for later.

The summary tree was renamed to `unresolved` and carries an honest note when the resolution
pass did not run. The cockpit — the page the owner actually opens — kept the word "Queued",
inlined from `dashboard.app.js`, and bound its tile to `counts.unknown` (unclassified
integrations) rather than to `counts.coverage.queued` (the unresolved endpoint rows the tree
counts). So the two surfaces disagreed on both the word and the number.

`coverage: "queued"` stays as the drift.json field name — this is presentation only.
"""
import json
import re

from agent.lib.dashboard_render import render_dashboard


def _inv(endpoints=()):
    return {"generated": "2026-08-14",
            "repos": [{"path": "svc-a", "endpoints": list(endpoints)}]}


def _audit(findings=()):
    return {"generated": "2026-08-14", "findings": list(findings),
            "counts": {"DEPRECATED": 0, "REVIEW": 0, "reposAffected": 0},
            "coverage": {"notes": []}}


def _ep(**kw):
    e = {"vendor": "Unknown external", "domain": "api.example.com", "version": None,
         "files": ["a.php:1"], "hostClass": "api-lead"}
    e.update(kw)
    return e


def _blob(html):
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    assert m, "drift-data blob not found"
    return json.loads(m.group(1).replace("\\u003c", "<"))


def test_the_cockpit_never_says_queued():
    """A queue on the page is a promise to do work later. The scan either settled the host,
    or says plainly that nobody looked — there is no third state worth the word."""
    html = render_dashboard(_inv([_ep()]), _audit(), "2026-08-14")
    assert "Queued" not in html, \
        "the cockpit still renders the word 'Queued' (inlined from dashboard.app.js)"


def test_the_unresolved_tile_counts_the_same_rows_the_tree_does():
    """The tile was bound to counts.unknown — unclassified INTEGRATIONS — while the tree
    counts counts.coverage.queued — unresolved ENDPOINT ROWS. Two partitions, one label:
    a resolution pass could settle every row and the tile would still show a number."""
    src = open("agent/assets/dashboard.app.js", encoding="utf-8").read()
    tile = re.search(r'\{key:"unknown",[^}]*\}', src)
    assert tile, "the unresolved tile is gone — update this test with its new key"
    assert "c.unknown" not in tile.group(0), \
        f"tile still bound to counts.unknown (a different partition): {tile.group(0)}"
    assert "coverage" in tile.group(0), \
        f"tile does not read counts.coverage.queued: {tile.group(0)}"


def test_the_cockpit_says_when_the_resolution_pass_did_not_run():
    """`resolutionRan: false` means nobody has looked at these hosts yet. The tree says so;
    the cockpit said nothing, so the same scan read as 'pending' on one page and as an
    unexplained number on the other. Cannot-see is not clean on either surface."""
    html = render_dashboard(_inv([_ep()]), _audit(), "2026-08-14")
    assert _blob(html).get("resolutionRan") is False, "fixture should have an unresolved pass"
    assert "resolution pass did not run" in html, \
        "the cockpit does not carry the honesty note the tree already renders"

# tests/test_probabilistic_render.py
from agent.lib.probabilistic_render import render_probabilistic

_CMP = {"tallies": {"agree": 3, "aiOnly": 2, "toolOnly": 1, "reposReadByAI": 20, "reposScanned": 20},
        "notCrossChecked": [],
        "byRepo": [{"repo": "myerapi", "agree": ["ebay"], "toolOnly": [],
                    "aiOnly": [{"vendor": "Marketplacer", "endpoint": "api/v2/adverts",
                                "file": "src/Myer/Get.php", "line": "9", "retired": "unknown",
                                "note": "n"}]}]}
_META = {"reposRead": 20, "tokens": 782188, "now": "2026-07-31"}


def test_render_is_labelled_unverified_and_self_contained():
    html = render_probabilistic(_CMP, _META)
    assert "AI · unverified" in html
    assert "<script src" not in html and "cdn" not in html.lower()      # no CDN
    assert "782,188" in html or "782188" in html                        # token cost shown


def test_render_shows_tallies_and_the_leads():
    html = render_probabilistic(_CMP, _META)
    assert "Marketplacer" in html and "src/Myer/Get.php" in html        # the lead + its loc
    assert ">2<" in html or "aiOnly" in html                            # aiOnly tally surfaced


def test_render_links_back_to_the_certified_report():
    html = render_probabilistic(_CMP, _META)
    assert "dashboard.html" in html                                     # cross-link to certified


def test_render_names_not_cross_checked_repos():
    cmp2 = {**_CMP, "notCrossChecked": ["brokenRepo"],
            "tallies": {**_CMP["tallies"], "reposReadByAI": 19}}
    html = render_probabilistic(cmp2, _META)
    assert "brokenRepo" in html and "not cross-checked" in html.lower()


def test_render_escapes_scan_strings():
    evil = {"tallies": {"agree": 0, "aiOnly": 1, "toolOnly": 0, "reposReadByAI": 1, "reposScanned": 1},
            "notCrossChecked": [],
            "byRepo": [{"repo": "r", "agree": [], "toolOnly": [],
                        "aiOnly": [{"vendor": "<script>alert(1)</script>", "endpoint": "e",
                                    "file": "f", "line": "1", "retired": "no", "note": ""}]}]}
    html = render_probabilistic(evil, _META)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_is_deterministic():
    assert render_probabilistic(_CMP, _META) == render_probabilistic(_CMP, _META)

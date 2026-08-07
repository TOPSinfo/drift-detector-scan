from agent.eval.render import render_scorecard


def _sc(passed=True):
    return {"category": "ebay", "now": "2026-07-16",
            "repos": [{"repo": "o/ebay-sdk-php", "detected": True, "via": "sdk",
                       "miss_mode": None, "noise": 3, "version_rate": 0.5,
                       "sunset_expected": True, "sunset_hit": True, "errored": False}],
            "summary": {"recall": {"passed": 1, "total": 1, "endpoint": 0, "sdk_only": 1,
                                   "known_miss": 0, "holdout": 0},
                        "noise": {"median": 3, "max": 3}, "version_rate": 0.5,
                        "sunset_match": {"expected": 1, "hit": 1}, "errored": 0},
            "gate": {"passed": passed, "failures": [] if passed else ["o/x"]}}


def test_table_shows_recall_gate_and_metrics():
    out = render_scorecard(_sc(passed=True))
    assert "ebay" in out
    assert "RECALL" in out and "PASS" in out
    assert "1/1" in out
    assert "noise" in out.lower() and "sunset" in out.lower() and "version" in out.lower()


def test_table_shows_fail_when_gate_fails():
    out = render_scorecard(_sc(passed=False))
    assert "FAIL" in out

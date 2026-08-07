# tests/test_probabilistic.py
from agent.lib.probabilistic import compare, norm


def _ai(repos):
    return {"meta": {"reposRead": len(repos), "tokens": 1000}, "repos": repos}


def test_norm_reduces_vendor_to_first_token_lowercased():
    assert norm("Amazon SP-API") == "amazon"
    assert norm("eBay") == "ebay"
    assert norm("THE ICONIC (SellerCenter)") == "the"


def test_compare_classifies_agree_aionly_toolonly_per_repo():
    certified = [
        {"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]},
        {"repo": "r1", "vendor": "Amazon SP-API", "classified": True, "files": ["b.php:2"]},
    ]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": [
        {"vendor": "eBay", "endpoint": "GetX", "file": "a.php", "line": "1", "retired": "no"},
        {"vendor": "Kogan", "endpoint": "list", "file": "k.php", "line": "9", "retired": "unknown"},
    ]}])
    out = compare(ai, certified)
    assert out["tallies"] == {"agree": 1, "aiOnly": 1, "toolOnly": 1,
                              "reposReadByAI": 1, "reposScanned": 1}
    repo = out["byRepo"][0]
    assert repo["repo"] == "r1"
    assert repo["agree"] == ["ebay"]
    assert repo["toolOnly"] == ["amazon"]
    assert [x["vendor"] for x in repo["aiOnly"]] == ["Kogan"]      # leads keep the full record


def test_repo_the_ai_did_not_read_is_named_not_cross_checked():
    certified = [{"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]},
                 {"repo": "r2", "vendor": "Shopify", "classified": True, "files": ["c.php:3"]}]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": [
        {"vendor": "eBay", "endpoint": "x", "file": "a.php", "line": "1", "retired": "no"}]}])
    out = compare(ai, certified)
    assert out["tallies"]["reposScanned"] == 2 and out["tallies"]["reposReadByAI"] == 1
    assert out["notCrossChecked"] == ["r2"]


def test_unclassified_certified_endpoints_are_ignored():
    certified = [{"repo": "r1", "vendor": "Unknown", "classified": False, "files": ["a.php:1"]}]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": []}])
    out = compare(ai, certified)
    assert out["tallies"]["toolOnly"] == 0


def test_both_blind_repo_surfaces_as_not_cross_checked_via_scanned_repos():
    # blindrepo has NO classified certified endpoint (a deterministic blind-spot) AND is absent
    # from ai_results["repos"] (the AI also failed to read it). Without the authoritative
    # scanned_repos list it would vanish from reposScanned/notCrossChecked/byRepo entirely —
    # "cannot see" must never present as "clean".
    certified = [{"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]}]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": [
        {"vendor": "eBay", "endpoint": "x", "file": "a.php", "line": "1", "retired": "no"}]}])
    out = compare(ai, certified, scanned_repos=["blindrepo", "r1"])
    assert out["tallies"]["reposScanned"] == 2
    assert "blindrepo" in out["notCrossChecked"]


def test_compare_without_scanned_repos_is_unchanged():
    # existing behavior (no scanned_repos arg) must be identical to before this change.
    certified = [{"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]},
                 {"repo": "r2", "vendor": "Shopify", "classified": True, "files": ["c.php:3"]}]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": [
        {"vendor": "eBay", "endpoint": "x", "file": "a.php", "line": "1", "retired": "no"}]}])
    out = compare(ai, certified)
    assert out["tallies"]["reposScanned"] == 2 and out["tallies"]["reposReadByAI"] == 1
    assert out["notCrossChecked"] == ["r2"]


def test_compare_is_deterministic():
    certified = [{"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]}]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": [
        {"vendor": "Kogan", "endpoint": "x", "file": "k.php", "line": "9", "retired": "unknown"},
        {"vendor": "MyDeal", "endpoint": "y", "file": "m.php", "line": "3", "retired": "unknown"}]}])
    assert compare(ai, certified) == compare(ai, certified)
    # aiOnly leads are sorted by vendor for stable output
    assert [x["vendor"] for x in compare(ai, certified)["byRepo"][0]["aiOnly"]] == ["Kogan", "MyDeal"]

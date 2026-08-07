"""The ad-hoc / just-in-time MIDDLE tier: pure-logic tests (below the artifact) + the anti-gaming
claims-scope guard, proven to FAIL on the gaming vector before it passes (CLAUDE.md principle 5)."""
from agent.lib import adhoc
from agent import absorb


def test_compare_restricts_shaped_actions_to_claimed_locs():
    adhoc_drift = {"actions": [
        # real drift.json vendor actions carry `files` as {href, loc} DICTS, not plain strings
        {"ref": "Walmart", "date": "2026-06-30", "files": [{"loc": "src/A.php:15", "href": "..."}]},
        {"ref": "Walmart", "date": None,          "files": ["src/B.php:20"]},   # plain-string form also supported
        {"ref": "eBay",    "date": "2026-01-01", "files": [{"loc": "src/Z.php:99"}]},   # NOT claimed → excluded
    ]}
    gate = {"attributedBefore": 1, "attributedAfter": 3, "residueBefore": 8, "residueAfter": 6,
            "claims": {"met": ["src/A.php:15", "src/B.php:20"], "missing": []},
            "invented": [], "unclaimed": [], "problems": []}
    out = adhoc.compare(adhoc_drift, ["src/A.php:15", "src/B.php:20"], gate, [{"id": "adhoc/r/1"}], "r")
    shaped_locs = set().union(*(adhoc._action_locs(a["files"]) for a in out["shaped"]))
    assert shaped_locs == {"src/A.php:15", "src/B.php:20"}   # eBay (unclaimed) excluded; dict + string forms both matched
    assert out["datedCount"] == 1                     # only the dated Walmart action
    assert out["attributedNew"] == 2                  # from the gate delta (3 - 1)
    assert out["problems"] == []


def test_compare_flags_over_broad_shape_as_problem():
    gate = {"attributedBefore": 1, "attributedAfter": 9, "invented": ["Shopify"],
            "unclaimed": ["src/X.php:1"], "claims": {"met": [], "missing": []}, "problems": ["residue grew"]}
    out = adhoc.compare({"actions": []}, [], gate, [], "r")
    assert out["problems"]      # invented + unclaimed + the gate's own problem → caller must NOT validate


def test_bundle_hash_binds_to_the_certified_scan():
    import hashlib
    import json
    cert = {"counts": {"fixes": 3}, "actions": []}
    b = adhoc.bundle(cert, [{"repo": "r"}], "2026-08-06")
    assert b["schemaVersion"] == "drift-adhoc/v1"
    assert b["meta"]["driftJsonSha256"] == hashlib.sha256(
        json.dumps(cert, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    # a different certified scan → a different hash (the staleness guard)
    assert (adhoc.bundle({"counts": {"fixes": 4}}, [], "2026-08-06")["meta"]["driftJsonSha256"]
            != b["meta"]["driftJsonSha256"])


def test_claims_scope_guard_rejects_the_gaming_vector():
    # A claim naming a line the brief never flagged as blind is scan-first-claim-what-fired — the
    # exact way an autonomous author makes the gate's `unclaimed` check vacuous.
    residue = ["src/A.php:15", "src/B.php:20"]
    assert absorb.check_claims_in_scope(["src/A.php:15"], residue) == []          # in scope → ok
    bad = absorb.check_claims_in_scope(["src/A.php:15", "src/EVIL.php:1"], residue)
    assert bad and "src/EVIL.php:1" in bad[0]                                     # out of scope → rejected

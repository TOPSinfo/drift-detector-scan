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
    """The hash must be over the BYTES OF drift.json ON DISK, so `sha256sum drift.json` — the
    tool every other digest in this project is checked with — reproduces it. It used to hash a
    canonical re-dump of the parsed dict, which matches no file anyone can point at."""
    import hashlib
    import json
    cert = {"counts": {"fixes": 3}, "actions": []}
    raw = json.dumps(cert, indent=2).encode("utf-8")          # the file, as written
    b = adhoc.bundle(cert, [{"repo": "r"}], "2026-08-06", certified_bytes=raw)
    assert b["schemaVersion"] == "drift-adhoc/v1"
    assert b["meta"]["driftJsonSha256"] == hashlib.sha256(raw).hexdigest()
    # a different certified scan → a different hash (the staleness guard)
    other = json.dumps({"counts": {"fixes": 4}}, indent=2).encode("utf-8")
    assert (adhoc.bundle({"counts": {"fixes": 4}}, [], "2026-08-06",
                         certified_bytes=other)["meta"]["driftJsonSha256"]
            != b["meta"]["driftJsonSha256"])


def test_bundle_hashes_the_file_bytes_not_a_re_serialization():
    """Pins the exact bug. This pretty file and its canonical re-dump differ byte-wise (indent,
    key order, trailing newline), so the two digests differ — and only the file-bytes one can be
    verified by a human with sha256sum."""
    import hashlib
    import json
    cert = {"b": 2, "a": {"nested": "\u00e9"}}
    raw = (json.dumps(cert, indent=2) + "\n").encode("utf-8")
    redump = json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() != hashlib.sha256(redump).hexdigest(), \
        "fixture is not discriminating"
    got = adhoc.bundle(json.loads(raw), [], "2026-08-14",
                       certified_bytes=raw)["meta"]["driftJsonSha256"]
    assert got == hashlib.sha256(raw).hexdigest(), "not the file bytes"
    assert got != hashlib.sha256(redump).hexdigest(), "still hashing a re-serialization"


def test_claims_scope_guard_rejects_the_gaming_vector():
    # A claim naming a line the brief never flagged as blind is scan-first-claim-what-fired — the
    # exact way an autonomous author makes the gate's `unclaimed` check vacuous.
    residue = ["src/A.php:15", "src/B.php:20"]
    assert absorb.check_claims_in_scope(["src/A.php:15"], residue) == []          # in scope → ok
    bad = absorb.check_claims_in_scope(["src/A.php:15", "src/EVIL.php:1"], residue)
    assert bad and "src/EVIL.php:1" in bad[0]                                     # out of scope → rejected

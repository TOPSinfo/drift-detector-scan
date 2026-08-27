"""The delta must say what it compared against, and the summary facts must be extracted once.

On a real fleet's FIRST run the delta reported 349 `new` and 0 `resolved`. Rendered as
"🆕 349 new · ✅ 0 resolved" that reads as a catastrophic week; it was the first measurement.
Nothing in the payload distinguished the two. `catalogDelta` already carries `comparedAgainst`
and coverage_digest.py relies on it for exactly this — the findings delta never got the field.
"""
from agent.lib import digest, findings_state


def _audit(*refs, generated="2026-08-27"):
    return {"generated": generated,
            "findings": [{"ref": r, "kind": "cve", "status": "DEPRECATED", "repo": "a",
                          "id": r, "detail": r} for r in refs]}


# ── Task 1: the delta names the scan it compared against ──────────────────────────────────────

def test_a_first_scan_compares_against_nothing(tmp_path):
    audit = _audit("npm/axios")
    findings_state.apply_lifecycle(audit, str(tmp_path), "2026-08-27")
    assert audit["delta"]["comparedAgainst"] is None, (
        "a first scan claimed to have compared against something")


def test_a_second_scan_names_the_first(tmp_path):
    """Derived from the state's own `last_seen`, so it works on state files written before this
    field existed — no migration, and no second place recording the same fact."""
    findings_state.apply_lifecycle(_audit("npm/axios"), str(tmp_path), "2026-08-20")
    audit = _audit("npm/axios", "npm/lodash")
    findings_state.apply_lifecycle(audit, str(tmp_path), "2026-08-27")
    assert audit["delta"]["comparedAgainst"] == "2026-08-20"
    assert len(audit["delta"]["new"]) == 1, "only lodash is new on the second run"


# ── Task 2: one extraction ────────────────────────────────────────────────────────────────────

_PAYLOAD = {
    "generated": "2026-08-27",
    "counts": {"fixes": 12, "reposAffected": 16, "reposScanned": 18,
               "byOwner": {"devops": {"fixes": 10, "review": 30},
                           "developer": {"fixes": 2, "review": 4}}},
    "delta": {"new": [1, 2, 3], "resolved": [1], "comparedAgainst": "2026-08-20"},
    "actions": [
        {"kind": "sunset", "ref": "eBay", "unit": "svcs.ebay.com", "date": "2025-02-05",
         "status": "DEPRECATED", "file_count": 4, "finding_count": 4},
        {"kind": "cve", "ref": "npm/axios", "date": None, "status": "DEPRECATED",
         "file_count": 9, "finding_count": 9},
        {"kind": "sunset", "ref": "Walmart", "unit": "/v3/insights", "date": "2027-02-06",
         "status": "REVIEW", "file_count": 1, "finding_count": 1},
        {"kind": "cve", "ref": "npm/lodash", "date": None, "status": "REVIEW",
         "file_count": 2, "finding_count": 2},
    ],
    "catalog": [{"vendor": "UPS", "verdict": "UNAUDITED", "callSites": 1},
                {"vendor": "Stripe", "verdict": "CURRENT", "callSites": 9}],
    "shapes": [{"repo": "a", "verdict": "UNKNOWN"}, {"repo": "b", "verdict": "KNOWN"}],
}


def test_every_figure_comes_from_the_payload():
    f = digest.summary_facts(_PAYLOAD)
    assert f["fixes"] == _PAYLOAD["counts"]["fixes"]
    assert f["review"] == 34                     # summed across owners, not invented
    assert (f["repos_affected"], f["repos_scanned"]) == (16, 18)
    assert (f["new"], f["resolved"]) == (3, 1)
    assert f["compared_against"] == "2026-08-20"


def test_the_most_urgent_is_the_earliest_dated_retirement():
    """Not the first action, and not a CVE — a CVE has no date, and 'most urgent' means what dies
    first, not what is worst."""
    u = digest.summary_facts(_PAYLOAD)["urgent"]
    assert u["ref"] == "eBay svcs.ebay.com" and u["date"] == "2025-02-05" and u["sites"] == 4


def test_do_first_is_capped_at_three_and_keeps_payload_order():
    f = digest.summary_facts(_PAYLOAD)
    assert [a["ref"] for a in f["do_first"]] == ["eBay", "npm/axios", "Walmart"]


def test_blind_spots_are_named_not_merely_counted():
    """`counts.unaudited` exists, but a reader can only act on the NAMES."""
    f = digest.summary_facts(_PAYLOAD)
    assert f["unaudited"] == [{"vendor": "UPS", "call_sites": 1}]
    assert f["unknown_repos"] == ["a"]


def test_a_clean_payload_yields_zeroes_not_absences():
    """Every key present on a clean fleet, so a renderer never has to guess whether a missing key
    means zero or means the extractor changed under it."""
    f = digest.summary_facts({"generated": "2026-08-27", "counts": {}, "delta": {},
                              "actions": [], "catalog": [], "shapes": []})
    assert f["fixes"] == 0 and f["do_first"] == [] and f["unaudited"] == []
    assert f["urgent"] is None and f["compared_against"] is None


def test_leads_is_injected_never_read_from_disk():
    """The AI plane's count is a PARAMETER. summary_facts stays a pure function of the payload —
    reading leads.json here would make it untestable and couple the certified plane to the
    probabilistic one."""
    assert digest.summary_facts(_PAYLOAD, leads=7)["leads"] == 7
    assert digest.summary_facts(_PAYLOAD)["leads"] is None

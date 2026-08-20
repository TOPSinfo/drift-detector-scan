"""Attestation provenance + the re-attestation TTL.

An AI 'no-retirement-found' is weaker than a human's — a missed sunset renders green and nobody
re-checks green — so it must be (a) marked distinctly (`by: ai-research`) and (b) governed by the
same staleness TTL as any attestation, so it expires and re-surfaces for research.
"""
from agent.lib import catalog_coverage as cc


def test_ai_provenance_flows_and_defaults_to_human():
    att = {"AiVendor": {"checked": "2026-08-10", "source": "https://x", "note": "", "by": "ai-research"},
           "HumanVendor": {"checked": "2026-08-10", "source": "https://y", "note": ""}}  # no `by`
    rows = {r["vendor"]: r for r in cc.build(
        [{"vendor": "AiVendor", "classified": True, "files": ["a:1"]},
         {"vendor": "HumanVendor", "classified": True, "files": ["b:1"]}], [], att, "2026-08-11")}
    assert rows["AiVendor"]["by"] == "ai-research"
    assert rows["HumanVendor"]["by"] == "human"        # absent provenance is a human attestation


def test_attestation_goes_stale_past_the_ttl():
    att = {"V": {"checked": "2026-08-10", "source": "https://x", "note": "", "by": "ai-research"}}
    assert cc.verdict_for("V", att, "2026-08-20")[0] == cc.CURRENT     # 10 days — fresh
    assert cc.verdict_for("V", att, "2027-01-01")[0] == cc.STALE       # > 90 days — must re-check


# ── a vendor whose ENTIRE API is catalogued as retired has nothing left to audit ──
# Found working the freshness backlog: the work-order was asking a human to "log into the
# MyDeal seller portal and paste the changelog" for a marketplace catalogued as shut down on
# 2025-09-30, and the same for MySale and Catch. That task can never succeed — the portal is
# gone with the company — so those vendors sat on the list permanently.
#
# verdict_for() reads ONLY attestations, so a whole-API (`version: "*"`) retirement, however
# well sourced, left the vendor UNAUDITED. But "unaudited" means "0 findings here is not
# evidence of health", and for these vendors findings are emphatically not zero: the `*`
# entry flags every call-site. There is nothing further to check.

def test_whole_api_retirement_removes_a_vendor_from_the_unaudited_worklist():
    sun = [{"vendor": "DeadMarket", "version": "*", "retires": "2025-09-30",
            "source": "https://example.test/closure"}]
    rows = {r["vendor"]: r for r in cc.build(
        [{"vendor": "DeadMarket", "classified": True, "file_count": 44, "files": ["a:1"]}],
        sun, {}, "2026-08-20")}                       # NO attestation for it
    r = rows["DeadMarket"]
    assert r["verdict"] != cc.UNAUDITED, "a dead vendor cannot be 'not yet checked'"
    assert "whole-api-retired" in r["reasons"], "and it must say WHY it is off the list"


def test_a_version_scoped_retirement_does_not_clear_the_vendor():
    """Only a WHOLE-API retirement settles it. One dead operation on a live API says nothing
    about the rest of that vendor's surface, so it stays on the work-list."""
    sun = [{"vendor": "LiveVendor", "version": "v1", "retires": "2025-09-30",
            "source": "https://example.test/x"}]
    rows = {r["vendor"]: r for r in cc.build(
        [{"vendor": "LiveVendor", "classified": True, "file_count": 5, "files": ["a:1"]}],
        sun, {}, "2026-08-20")}
    assert rows["LiveVendor"]["verdict"] == cc.UNAUDITED


def test_an_undated_whole_api_deprecation_also_clears_it():
    """`status: deprecated-no-date` is still a whole-API retirement — the vendor is going away
    and we have said so. Requiring a date would keep undated closures on the list forever."""
    sun = [{"vendor": "GoneSoon", "version": "*", "status": "deprecated-no-date",
            "source": "https://example.test/y"}]
    rows = {r["vendor"]: r for r in cc.build(
        [{"vendor": "GoneSoon", "classified": True, "file_count": 3, "files": ["a:1"]}],
        sun, {}, "2026-08-20")}
    assert rows["GoneSoon"]["verdict"] != cc.UNAUDITED

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


def test_a_vendor_whose_deprecation_page_is_behind_partner_access_is_BLOCKED_not_UNAUDITED():
    """Three marketplaces (Temu, THE ICONIC, Mirakl) publish retirements only behind a
    partner/seller login nobody on this side holds. They sat in the same UNAUDITED bucket as
    "nobody got around to it", so the report could not tell an unworked item from one that is
    externally blocked — and the freshness work-order kept asking a human to open a door they
    have no key to. That is the same mistake `whole-api-retired` already fixed for dead
    marketplaces: a task that can never succeed must not stay on a recurring list.

    BLOCKED is NOT an attestation. It never becomes CURRENT, its call-sites keep counting as
    unchecked exposure, and it must carry the gate page that was actually hit."""
    att = {"Temu": {"checked": "2026-08-21", "source": "https://partner.temu.com/",
                    "blocked": "seller portal login required; no public deprecation page"}}
    verdict, reasons, checked = cc.verdict_for("Temu", att, "2026-08-21")
    assert verdict == cc.BLOCKED
    assert reasons == [cc.ACCESS_BLOCKED]
    assert checked == "2026-08-21"          # we DID check — and were refused


def test_BLOCKED_keeps_counting_as_unchecked_exposure_and_stays_out_of_CURRENT():
    """Principle 1: a documented blind spot is still a blind spot. Naming WHY we are blind
    must not quietly convert the vendor's call-sites into audited ones."""
    eps = [{"vendor": "Temu", "classified": True, "file_count": 7, "domain": "temu.test"}]
    att = {"Temu": {"checked": "2026-08-21", "source": "https://partner.temu.com/",
                    "blocked": "seller portal login required"}}
    recs = cc.build(eps, [], att, "2026-08-21")
    row = next(r for r in recs if r["vendor"] == "Temu")
    assert row["verdict"] == cc.BLOCKED
    assert row["blocked"] == "seller portal login required"
    s = cc.summary(recs)
    assert s["blocked"] == 1 and s["current"] == 0 and s["unaudited"] == 0
    assert s["unauditedCallSites"] == 7      # still exposure nobody has checked


def test_the_LOADER_carries_blocked_through_from_the_yaml(tmp_path):
    """REGRESSION: `blocked:` was implemented in verdict_for and the unit tests passed a dict
    straight to it — so nothing exercised load_attestations, which whitelists the fields it
    copies out of the YAML. It silently dropped `blocked`, and three vendors whose docs are
    genuinely unreachable came back CURRENT: the strongest possible claim, from evidence that
    said the opposite. Caught by running it on the real catalog, not by the unit tests."""
    p = tmp_path / "att.yaml"
    p.write_text("- vendor: Temu\n  checked: '2026-08-21'\n  source: https://seller.temu.com/\n"
                 "  blocked: 'seller portal login required'\n", encoding="utf-8")
    att = cc.load_attestations(str(p))
    assert att["Temu"]["blocked"] == "seller portal login required"
    assert cc.verdict_for("Temu", att, "2026-08-21")[0] == cc.BLOCKED

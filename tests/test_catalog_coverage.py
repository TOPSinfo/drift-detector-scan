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

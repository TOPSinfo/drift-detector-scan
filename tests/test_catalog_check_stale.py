"""Guards the stale-attestation loop (Fable move #4): an attestation past its 90-day TTL is
re-research work, surfaced fleet-wide. Without it, a vendor reconciled once and then forgotten
looks identical to never-checked — the batch `research --vendors` pass would quietly rot at 90 days."""
from agent import catalog_check


def test_stale_flags_past_ttl_not_fresh():
    atts = {
        "OldVendor": {"checked": "2026-01-01", "source": "u", "by": "ai-research"},   # >90d before now
        "FreshVendor": {"checked": "2026-08-01", "source": "u", "by": "human"},        # <90d
    }
    stale = catalog_check.stale_attestations(atts, now="2026-08-11")
    names = {s["vendor"] for s in stale}
    assert "OldVendor" in names
    assert "FreshVendor" not in names
    assert all(s["kind"] == "stale-attestation" for s in stale)


def test_no_stale_when_all_fresh():
    atts = {"FreshVendor": {"checked": "2026-08-10", "source": "u", "by": "human"}}
    assert catalog_check.stale_attestations(atts, now="2026-08-11") == []


def test_check_all_appends_stale_records_and_flags_attention():
    atts = {"OldVendor": {"checked": "2026-01-01", "source": "u", "by": "ai-research"}}
    report = catalog_check.check_all(fetch=lambda u: "", catalog=[], attestations=atts, now="2026-08-11")
    assert any(r.get("kind") == "stale-attestation" and r["vendor"] == "OldVendor" for r in report)
    assert catalog_check.needs_attention(report)


def test_render_shows_stale_section_with_rerun_hint():
    report = [{"vendor": "OldVendor", "kind": "stale-attestation", "checked": "2026-01-01",
               "by": "ai-research"}]
    out = catalog_check.render(report)
    assert "past the freshness TTL" in out
    assert "OldVendor" in out
    assert 'research --vendors "OldVendor"' in out

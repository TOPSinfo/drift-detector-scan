import pytest
from agent.lib import verify


def _clean():
    return {"counts": {"fixes": 0, "sunsets": 0}, "endpoints": [], "findings": [], "catalog": []}


def test_a_clean_payload_passes():
    verify.check_ai_firewall(_clean())


@pytest.mark.parametrize("payload", [
    {"counts": {}, "endpoints": [{"domain": "a.com", "origin": "ai"}], "findings": [], "catalog": []},
    {"counts": {}, "endpoints": [], "findings": [{"vendor": "X", "origin": "lead"}], "catalog": []},
    {"counts": {}, "endpoints": [], "findings": [], "catalog": [{"vendor": "X", "by": "lead"}]},
    {"counts": {}, "endpoints": [{"domain": "a.com", "tier": "ai-shaped"}], "findings": [],
     "catalog": []},
])
def test_an_ai_record_in_the_certified_payload_is_a_violation(payload):
    """Until now the firewall between certified findings and AI output WAS file separation: the AI
    lived in a different HTML file and verify only covered the certified ones. Once they share a
    document that structural guarantee is gone, so it has to become an executable check —
    otherwise 'merge the AI tab into the dashboard' silently weakens the tool's central claim."""
    with pytest.raises(verify.Violation) as exc:
        verify.check_ai_firewall(payload)
    assert exc.value.check == "ai-firewall"


def test_the_firewall_runs_as_part_of_verify_payload():
    # "actions": [] is required here even though this test targets the AI firewall: earlier
    # checks in verify_payload's tuple (check_tile_counts, check_row_labels_distinct) index
    # payload["actions"] directly and would raise an unrelated KeyError before check_ai_firewall
    # ever runs on a payload that omits it.
    dirty = {"counts": {}, "actions": [], "endpoints": [{"domain": "a.com", "origin": "ai"}],
             "findings": [], "catalog": []}
    names = [v.check for v in verify.verify_payload(dirty, [])]
    assert "ai-firewall" in names


def test_ai_provenance_on_an_ATTESTATION_is_still_allowed():
    """`by: ai-research` on a catalog attestation is a LEGITIMATE, gate-validated provenance marker
    (it already ships on ~40 vendors). The firewall targets AI-shaped FINDINGS and ENDPOINTS, not
    the honest labelling of who checked a vendor's page."""
    ok = _clean()
    ok["catalog"] = [{"vendor": "Mailgun", "verdict": "CURRENT", "by": "ai-research"}]
    verify.check_ai_firewall(ok)

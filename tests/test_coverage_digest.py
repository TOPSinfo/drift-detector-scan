"""The management digest — the absorption scoreboard as a document someone can be sent.

A PROJECTION of drift.json, never a second computation. Every number here must be read from
the payload, because a digest that recomputes its own figures can disagree with the report it
summarises, and then the two artifacts quietly say different things to different readers.
`verify.check_digest_matches_coverage` is what enforces that; these tests cover what it says.
"""
from agent.lib import coverage_digest


def _payload(**over):
    p = {
        "generated": "2026-08-24",
        "catalogSummary": {"current": 58, "stale": 4, "unaudited": 12, "blocked": 3,
                           "internal": 2, "accepted": 0, "unauditedCallSites": 271},
        "catalogDelta": {"comparedAgainst": "2026-08-17", "newlyAttested": ["eBay"],
                         "newlyStale": [], "newlyDetected": ["Klarna"], "noLongerDetected": []},
        "catalog": [],
    }
    p.update(over)
    return p


def test_the_headline_states_attested_over_detected():
    """The one number the PM asked for: how many of the vendors we actually call has anybody
    checked. 58 CURRENT + 2 INTERNAL settled, out of 79 detected."""
    md = coverage_digest.render(_payload(), now="2026-08-24")
    assert "60 of 79" in md


def test_the_unchecked_call_sites_are_stated_not_just_the_vendor_count():
    """A vendor count flattens exposure: twelve unaudited vendors behind three call-sites is a
    different morning than twelve behind 271."""
    assert "271" in coverage_digest.render(_payload(), now="2026-08-24")


def test_movement_since_the_last_scan_is_reported():
    md = coverage_digest.render(_payload(), now="2026-08-24")
    assert "eBay" in md and "2026-08-17" in md


def test_a_first_run_says_it_has_no_baseline_rather_than_showing_calm():
    """An empty movement section with no explanation reads as 'a quiet week'. It is not — it is
    'nothing to compare against', and the difference is the whole product."""
    md = coverage_digest.render(
        _payload(catalogDelta={"comparedAgainst": None, "newlyAttested": [], "newlyStale": [],
                               "newlyDetected": [], "noLongerDetected": []}),
        now="2026-08-24")
    assert "no previous scan" in md.lower()


def test_a_signed_disposition_names_its_approver_in_the_digest():
    """The point of recording a person is that the report says who. An unnamed waiver is just a
    suppression."""
    md = coverage_digest.render(_payload(catalog=[
        {"vendor": "AcmeBilling", "verdict": "INTERNAL", "callSites": 3,
         "approver": {"name": "Priya Shah", "role": "Head of Engineering",
                      "basis": "Built in-house; no external vendor lifecycle."},
         "expires": "2027-02-24"}]), now="2026-08-24")
    assert "Priya Shah" in md and "Head of Engineering" in md


def test_a_disposition_expiring_soon_is_surfaced():
    """A lapse that surprises someone is a lapse that gets rubber-stamped in a hurry. 60 days is
    enough notice to re-examine rather than re-sign."""
    md = coverage_digest.render(_payload(catalog=[
        {"vendor": "AcmeBilling", "verdict": "INTERNAL", "callSites": 3,
         "approver": {"name": "Priya Shah", "role": "Head of Engineering", "basis": "In-house."},
         "expires": "2026-09-30"}]), now="2026-08-24")
    assert "expiring" in md.lower() and "2026-09-30" in md


def test_an_accepted_risk_is_not_presented_as_covered():
    """ACCEPTED names a risk without measuring it. Listing it beside INTERNAL under one
    'signed off' heading would tell a manager the exposure is handled when it is not."""
    md = coverage_digest.render(_payload(
        catalogSummary={"current": 10, "stale": 0, "unaudited": 0, "blocked": 0,
                        "internal": 1, "accepted": 1, "unauditedCallSites": 7},
        catalog=[{"vendor": "ObscureCo", "verdict": "ACCEPTED", "callSites": 7,
                  "approver": {"name": "Priya Shah", "role": "Head of Engineering",
                               "basis": "Publishes no retirement notices anywhere findable."},
                  "expires": "2027-02-24"}]), now="2026-08-24")
    accepted_at = md.lower().index("obscureco")
    assert "still counted as unchecked" in md.lower()
    # and it must appear in a section that does NOT claim coverage
    assert "signed off — no further check possible" not in md[:accepted_at].lower()


# ── the invariant that keeps the digest honest ──

def test_a_faithful_digest_passes_verification():
    from agent.lib import verify
    payload = _payload()
    verify.check_digest_matches_coverage(coverage_digest.render(payload, now="2026-08-24"), payload)


def test_a_digest_whose_headline_disagrees_with_the_report_is_refused():
    """THE bug this exists to catch. A digest is mailed to people who will never open
    drift.json, so a figure that drifts from the report is a lie with a long half-life and no
    reader positioned to notice. Seeded by hand-editing the rendered count, which is exactly how
    it would happen — a template tweak, a rounding, a stale constant."""
    import pytest

    from agent.lib import verify
    payload = _payload()
    md = coverage_digest.render(payload, now="2026-08-24").replace("60 of 79", "79 of 79")
    with pytest.raises(verify.Violation) as e:
        verify.check_digest_matches_coverage(md, payload)
    assert "60" in str(e.value)


def test_a_digest_understating_the_blind_spot_is_refused():
    """The direction that matters most: under-reporting unchecked call-sites makes the backlog
    look smaller than it is, which is the failure mode this whole tool exists to prevent."""
    import pytest

    from agent.lib import verify
    payload = _payload()
    md = coverage_digest.render(payload, now="2026-08-24").replace("271", "27")
    with pytest.raises(verify.Violation):
        verify.check_digest_matches_coverage(md, payload)


# ── the command that produces the artifact CI mails ──

def test_the_cli_writes_a_digest_that_verifies_against_the_report(tmp_path):
    """End to end through the real entry point: drift.json in, coverage-digest.md out, and the
    invariant holding between them. The digest reads from drift.json — the CANONICAL report —
    rather than audit.json, so it can never quote a figure the contract does not carry."""
    import json

    from agent import cli
    from agent.lib import verify

    payload = _payload()
    (tmp_path / "drift.json").write_text(json.dumps(payload), encoding="utf-8")

    rc = cli.main(["coverage-report", "--state", str(tmp_path), "--now", "2026-08-24"])
    assert rc == 0
    md = (tmp_path / "coverage-digest.md").read_text(encoding="utf-8")
    verify.check_digest_matches_coverage(md, payload)
    assert "60 of 79" in md


def test_the_cli_says_so_when_there_is_no_report_yet(tmp_path):
    """A missing drift.json is 'no scan has run', not 'coverage is fine'."""
    from agent import cli
    assert cli.main(["coverage-report", "--state", str(tmp_path), "--now", "2026-08-24"]) == 2

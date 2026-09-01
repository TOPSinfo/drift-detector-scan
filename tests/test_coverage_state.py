"""Run-over-run movement in catalog coverage — the "is the backlog shrinking?" view.

`catalog_coverage` grades every vendor on a single scan. That answers "where are we" but not
"are we getting anywhere", which is the question a backlog is actually managed against.

The load-bearing decision here is what a FIRST run reports. Diffing against an absent state
file would present all 60 attestations as if they had just been earned, which is the same
class of lie as rendering an unread repo as clean: absence of a prior state is not evidence
that everything changed. A first run therefore reports no transitions at all.
"""
from agent.lib import coverage_state


def _rec(vendor, verdict, sites=1):
    return {"vendor": vendor, "verdict": verdict, "callSites": sites}


def test_the_first_run_reports_no_transitions(tmp_path):
    """No prior state means no comparison is possible — not that everything is new."""
    records = [_rec("Adyen", "CURRENT"), _rec("eBay", "UNAUDITED")]
    delta = coverage_state.apply(records, str(tmp_path), now="2026-08-24")
    assert delta["newlyAttested"] == []
    assert delta["newlyStale"] == []
    assert delta["newlyDetected"] == []
    assert delta["noLongerDetected"] == []
    assert delta["comparedAgainst"] is None      # says WHY it is empty, rather than implying calm


def test_the_first_run_still_records_state_so_the_second_run_can_compare(tmp_path):
    coverage_state.apply([_rec("Adyen", "CURRENT")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("Adyen", "STALE")], str(tmp_path), now="2026-11-24")
    assert delta["newlyStale"] == ["Adyen"]
    assert delta["comparedAgainst"] == "2026-08-24"


def test_a_vendor_that_became_attested_is_reported_as_newly_attested(tmp_path):
    coverage_state.apply([_rec("eBay", "UNAUDITED")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("eBay", "CURRENT")], str(tmp_path), now="2026-09-24")
    assert delta["newlyAttested"] == ["eBay"]


def test_an_in_house_disposition_counts_as_newly_attested(tmp_path):
    """INTERNAL settles a vendor just as CURRENT does, so signing one off is progress and must
    show as such — otherwise the backlog shrinks with nothing explaining why."""
    coverage_state.apply([_rec("AcmeBilling", "UNAUDITED")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("AcmeBilling", "INTERNAL")], str(tmp_path), now="2026-09-24")
    assert delta["newlyAttested"] == ["AcmeBilling"]


def test_a_brand_new_vendor_is_detected_not_credited_as_attested(tmp_path):
    """A vendor that shows up already catalogued was not absorbed this period — nobody did that
    work now. Counting it as newly-attested would credit the team with progress it did not make
    and make the digest's headline movement unreliable."""
    coverage_state.apply([_rec("Adyen", "CURRENT")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("Adyen", "CURRENT"), _rec("Stripe", "CURRENT")],
                                 str(tmp_path), now="2026-09-24")
    assert delta["newlyDetected"] == ["Stripe"]
    assert delta["newlyAttested"] == []


def test_a_vendor_that_stopped_being_called_is_reported(tmp_path):
    coverage_state.apply([_rec("Adyen", "CURRENT"), _rec("eBay", "UNAUDITED")],
                         str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("Adyen", "CURRENT")], str(tmp_path), now="2026-09-24")
    assert delta["noLongerDetected"] == ["eBay"]


def test_a_quiet_run_reports_no_movement(tmp_path):
    """The common case. A digest that manufactures movement every week teaches its reader to
    stop looking at it."""
    coverage_state.apply([_rec("Adyen", "CURRENT")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("Adyen", "CURRENT")], str(tmp_path), now="2026-08-31")
    assert delta["newlyAttested"] == [] and delta["newlyStale"] == []
    assert delta["newlyDetected"] == [] and delta["noLongerDetected"] == []
    assert delta["comparedAgainst"] == "2026-08-24"


# ── the wiring: the delta has to reach the report, not just exist as a function ──

def test_the_pipeline_records_coverage_movement_between_two_runs(tmp_path, monkeypatch):
    """A delta nobody wires in is a function with tests and no product. Two runs over the same
    state dir must leave a `catalogDelta` in the coverage block, and the FIRST must declare it
    had no baseline rather than reporting an empty-and-therefore-calm result."""
    import json
    import subprocess

    import agent.audit as audit_mod
    from agent.run import run_pipeline

    root = tmp_path / "repos"
    (root / "web").mkdir(parents=True)
    (root / "web" / "composer.json").write_text('{"require": {"php": "^7.4"}}')
    subprocess.run(["git", "init", "-q"], cwd=root / "web", check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=root / "web", check=True)
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)

    state = tmp_path / "state"
    for now in ("2026-07-15", "2026-07-22"):
        run_pipeline(str(root), str(state), now, engine="semgrep",
                     run=lambda args: json.dumps([]), http=lambda *a, **k: {})
        drift = json.loads((state / "drift.json").read_text())

    assert drift["catalogDelta"]["comparedAgainst"] == "2026-07-15"   # run 2 compared against run 1
    # the counts management reads must reach the CANONICAL report, not just audit.json — the
    # digest is a projection of drift.json, so anything absent here cannot be reported at all
    assert "catalogSummary" in drift
    assert (state / "coverage-state.json").exists()


def test_a_prior_scan_that_found_no_vendors_is_still_a_baseline(tmp_path):
    """Absence and emptiness are different states. A first scan detecting zero vendors is a real
    observation — "nothing was being called then" — and the next run must diff against it. The
    bug this guards: keying the no-baseline branch on an empty verdict map instead of a missing
    state file, which silently skipped the delta on every run following an empty scan."""
    coverage_state.apply([], str(tmp_path), now="2026-08-24")           # a real scan, zero vendors
    delta = coverage_state.apply([_rec("Stripe", "CURRENT")], str(tmp_path), now="2026-08-31")
    assert delta["comparedAgainst"] == "2026-08-24"
    assert delta["newlyDetected"] == ["Stripe"]


# ── BLOCKED movement ────────────────────────────────────────────────────────────────────────
# BLOCKED is not in SETTLED and is not STALE, so before these tests a vendor turning BLOCKED
# moved through the delta invisibly: newlyAttested no, newlyStale no, nothing. The one verdict
# whose fix requires somebody OUTSIDE the team — credentials, an account, an allow-list — was
# the one verdict that generated no signal at all.

def test_a_vendor_that_became_blocked_is_reported(tmp_path):
    coverage_state.apply([_rec("Mirakl", "UNAUDITED")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("Mirakl", "BLOCKED")], str(tmp_path), now="2026-09-01")
    assert delta["newlyBlocked"] == ["Mirakl"]


def test_a_vendor_that_was_already_blocked_is_not_re_reported(tmp_path):
    """The alert fires on CHANGE. A standing block repeated every scan is the never-empty list
    freshness.py refuses to produce — it stops being read, and then a real new block is missed."""
    coverage_state.apply([_rec("Temu", "BLOCKED")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("Temu", "BLOCKED")], str(tmp_path), now="2026-09-01")
    assert delta["newlyBlocked"] == []


def test_a_vendor_that_got_unblocked_is_reported_as_no_longer_blocked(tmp_path):
    """Somebody supplied access. That is the outcome this whole stream exists to produce, so it
    is worth saying out loud — and it is what closes the work-order."""
    coverage_state.apply([_rec("THE ICONIC", "BLOCKED")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("THE ICONIC", "CURRENT")], str(tmp_path), now="2026-09-01")
    assert delta["noLongerBlocked"] == ["THE ICONIC"]
    assert delta["newlyBlocked"] == []


def test_a_brand_new_vendor_that_arrives_already_blocked_is_reported_blocked(tmp_path):
    """DELIBERATE divergence from newlyAttested, which withholds credit for a first sighting
    because nobody did that work this period. Credit is not the question here: a blind spot is
    new TO US whenever it appears, and an admin who is never told about it cannot clear it.
    Reporting exposure on arrival is the same instinct as `cannot see` != `clean`."""
    coverage_state.apply([_rec("Adyen", "CURRENT")], str(tmp_path), now="2026-08-24")
    delta = coverage_state.apply([_rec("Adyen", "CURRENT"), _rec("Virtualstock", "BLOCKED")],
                                 str(tmp_path), now="2026-09-01")
    assert delta["newlyBlocked"] == ["Virtualstock"]
    assert delta["newlyDetected"] == ["Virtualstock"]      # still reported as a first sighting


def test_the_first_run_reports_no_blocked_movement(tmp_path):
    """No baseline means no movement, exactly as for every other transition."""
    delta = coverage_state.apply([_rec("Mirakl", "BLOCKED")], str(tmp_path), now="2026-08-24")
    assert delta["newlyBlocked"] == []
    assert delta["noLongerBlocked"] == []

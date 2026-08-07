from agent.lib import shapes

_PHP_KINDS = {"php": ["url", "path-literal", "sink", "path-assembly", "operation-marker"],
              "go": ["url", "path-literal", "operation-marker"]}      # go: NO egress signal
_EMPTY = {"pathLiterals": [], "sinks": []}


def test_a_language_without_egress_rules_can_never_be_silently_clean():
    """The bug Phase 2 exists to kill: no rules for a language produces no residue,
    so the repo used to look identical to a genuinely clean one."""
    cov = shapes.signal_coverage(["go"], _PHP_KINDS)
    v, reasons = shapes.verdict(attributed=0, residue=_EMPTY, coverage=cov)
    assert v == "UNKNOWN" and shapes.NO_EGRESS_SIGNAL in reasons


def test_full_coverage_and_no_residue_is_known():
    cov = shapes.signal_coverage(["php"], _PHP_KINDS)
    v, reasons = shapes.verdict(attributed=12, residue=_EMPTY, coverage=cov)
    assert v == "KNOWN" and reasons == []


def test_unattributed_path_is_always_a_miss():
    cov = shapes.signal_coverage(["php"], _PHP_KINDS)
    residue = {"pathLiterals": [{"sample": "/x/v0/y", "loc": "a.php:3"}], "sinks": []}
    v, reasons = shapes.verdict(attributed=99, residue=residue, coverage=cov)
    assert v == "UNKNOWN" and "config-driven-url" in reasons


def test_sinks_alone_do_not_condemn_a_fully_attributed_repo():
    """amazonspapi resolves 273 call-sites and still shows 7 curl sinks; we cannot
    link a sink to its endpoint without dataflow, so counting those as unknown would
    cry wolf on the repos we see best."""
    cov = shapes.signal_coverage(["php"], _PHP_KINDS)
    residue = {"pathLiterals": [], "sinks": [{"kind": "egress", "loc": "c.php:7"}] * 7}
    assert shapes.verdict(attributed=20, residue=residue, coverage=cov)[0] == "KNOWN"
    # ...but with nothing attributed, sinks ARE the evidence of blindness
    v, reasons = shapes.verdict(attributed=0, residue=residue, coverage=cov)
    assert v == "UNKNOWN" and "sdk-only-no-callsite" in reasons


def test_one_stray_file_does_not_make_a_language_meaningful():
    assert shapes.meaningful_languages({"php": 99, "go": 1}) == ["php"]
    assert set(shapes.meaningful_languages({"php": 5, "go": 5})) == {"go", "php"}


def test_residue_fingerprint_ignores_line_numbers_but_not_content():
    a = {"pathLiterals": [{"sample": "/x/v0/y", "loc": "a.php:3"}], "sinks": []}
    b = {"pathLiterals": [{"sample": "/x/v0/y", "loc": "a.php:41"}], "sinks": []}   # edit above
    c = {"pathLiterals": [{"sample": "/x/v9/z", "loc": "a.php:3"}], "sinks": []}    # NEW residue
    assert shapes.residue_fingerprint(a) == shapes.residue_fingerprint(b)
    assert shapes.residue_fingerprint(a) != shapes.residue_fingerprint(c)


def test_attestation_clears_the_verdict_then_lapses_when_residue_changes(tmp_path):
    cov = shapes.signal_coverage(["php"], _PHP_KINDS)
    residue = {"pathLiterals": [{"sample": "/x/v0/y", "loc": "a.php:3"}], "sinks": []}
    fp = shapes.residue_fingerprint(residue)
    shapes.attest(str(tmp_path), "svc", fp, resolved_by="human", date="2026-07-20")
    at = shapes.load_attestations(str(tmp_path))
    assert shapes.is_attested(at, "svc", fp)
    assert shapes.verdict(1, residue, cov, attested=True)[0] == "KNOWN"
    # new residue -> new fingerprint -> the old attestation no longer applies
    grew = {"pathLiterals": residue["pathLiterals"] + [{"sample": "/n/v1/z", "loc": "b.php:9"}],
            "sinks": []}
    assert not shapes.is_attested(at, "svc", shapes.residue_fingerprint(grew))


# --- scan profiles -------------------------------------------------------------

def _shape(verdict, reasons, coverage, paths=0):
    return {"repo": "r", "verdict": verdict, "reasons": reasons,
            "signalCoverage": coverage, "unattributedPaths": paths}


def test_profile_auto_when_the_tool_can_see_everything():
    sh = _shape("KNOWN", [], {"php": ["sink", "url"]})
    assert shapes.recommend_profile(sh)[0] == shapes.AUTO


def test_profile_hybrid_when_the_tool_names_what_it_missed():
    sh = _shape("UNKNOWN", ["config-driven-url"], {"php": ["sink", "url"]}, paths=3)
    profile, why = shapes.recommend_profile(sh)
    assert profile == shapes.HYBRID and "3 unattributed" in why


def test_profile_manual_when_a_language_has_no_egress_rules():
    """No rules means no residue means nothing to be confident about — an agent
    has to make first contact, not the tool."""
    sh = _shape("UNKNOWN", [shapes.NO_EGRESS_SIGNAL], {"go": ["url", "path-literal"]})
    profile, why = shapes.recommend_profile(sh)
    assert profile == shapes.MANUAL and "go" in why


def test_prescan_census_recommendation_needs_no_engine():
    kinds = {"php": ["sink", "path-assembly", "url"], "go": ["url"]}
    assert shapes.recommend_from_census({"php": 40}, kinds)[0] == shapes.AUTO
    assert shapes.recommend_from_census({"go": 40}, kinds)[0] == shapes.MANUAL
    assert shapes.recommend_from_census({}, kinds)[0] == shapes.AUTO      # nothing to scan

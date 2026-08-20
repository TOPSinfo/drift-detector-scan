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


# ── Honesty regressions: repos the scanner cannot actually read must say UNKNOWN ──
# Found by an independent inspection. All three are the same failure in different
# clothes: the tool reporting a clean bill for a repo it never really saw.

def test_real_ruleset_sdk_only_js_is_not_silently_known():
    """`signal_coverage` answers "do we SHIP a rule for this language", not "did this
    scan produce signal". Commit 26fe4a2 gave all 8 languages a sink rule, so against
    the REAL ruleset `no-egress-signal` can never fire — and a JS repo that resolved
    nothing and left no residue reports KNOWN.

    The existing guard passed only because it used a hand-written fixture in which Go
    had no sink. Pointing it at `rule_kinds_by_language(load_vendors())` is the point.
    """
    from agent.lib.vendors import load_vendors
    from agent.lib.vendor_rules import rule_kinds_by_language
    rk = rule_kinds_by_language(load_vendors())
    assert "sink" in rk.get("javascript", []), "precondition: the shipped ruleset has a JS sink"

    cov = shapes.signal_coverage(["javascript"], rk)
    v, reasons = shapes.verdict(0, {"pathLiterals": [], "sinks": []}, cov)
    assert v == "UNKNOWN", (
        f"a JS repo that attributed nothing and left no residue reported {v} "
        f"against the real ruleset — 'cannot see' rendering as 'clean'")


def test_a_jsx_only_repo_is_not_a_green_all_clear(tmp_path):
    """`.jsx`/`.vue`/`.svelte`/`.astro` are in neither _LANG_BY_EXT nor _CODE_ISH, so a
    React/Vue repo censuses EMPTY — no language to check coverage for, no unmodeled
    files to count — and sails through as KNOWN. Verified on a real scan: 3 vendor
    calls across .jsx and .vue, 2 detected, grade HIGH."""
    (tmp_path / "App.jsx").write_text("fetch('https://api.example-vendor.io/v1/x')\n")
    (tmp_path / "Cart.vue").write_text("<script>fetch('https://api.other.io/v1/y')</script>\n")
    counts, unmodeled = shapes.census(str(tmp_path))
    assert counts or unmodeled, (
        "a repo of .jsx/.vue files censused as nothing at all — neither modelled nor "
        "counted as unreadable")
    cov = shapes.signal_coverage(shapes.meaningful_languages(counts), {})
    v, _ = shapes.verdict(0, {"pathLiterals": [], "sinks": []}, cov, unmodeled=unmodeled)
    assert v == "UNKNOWN"


def test_a_repo_half_unreadable_is_not_known_just_because_the_other_half_read():
    """`unmodeled` was only held against a repo when coverage was EMPTY. A repo that is
    half Vue and half JS reads the JS, cannot read the Vue at all, and still reported
    KNOWN — the unreadable half silently written off because some other language
    happened to parse.

    Measured on a real scan: 1 modelled file + 1 unreadable .vue file, one vendor call
    found and one missed, verdict KNOWN, grade HIGH."""
    cov = {"javascript": ["sink", "url"]}
    v, reasons = shapes.verdict(1, {"pathLiterals": [], "sinks": []}, cov,
                                unmodeled=1, modeled=1)
    assert v == "UNKNOWN", "half the repo was unreadable and the verdict was still KNOWN"
    assert shapes.UNMODELED_LANGUAGE in reasons


def test_one_stray_unreadable_file_does_not_condemn_a_readable_repo():
    """The mirror: unmodeled files must clear the same meaningful-share bar languages do,
    or a single .vue snippet in a 200-file PHP app would cry wolf."""
    cov = {"php": ["sink", "url"]}
    v, _ = shapes.verdict(50, {"pathLiterals": [], "sinks": []}, cov,
                          unmodeled=1, modeled=200)
    assert v == "KNOWN"


# ── an uncatalogued vendor is a DIFFERENT blindness from having found nothing ──────
# REGRESSION (a fleet repo, found 2026-08-20): a repo whose whole purpose is a Temu
# integration reported `attributed: 0` and the reason `sdk-only-no-callsite`. Both were
# misleading. The scan HAD extracted https://openapi-b-global.temu.com/openapi/router at
# its own client class — it saw the endpoint perfectly. Temu simply is not in
# vendors.yaml, so the host classified as Unknown, and `attributed` counts only catalogued
# vendors.
#
# "We make calls we cannot trace" and "we found the call and cannot name the vendor" are
# different problems with different fixes — the first needs an idiom, the second needs a
# catalog entry. Reporting the first when it is the second sends the reader to the wrong
# work, and hides the single cheapest fix the tool has.

def test_an_unclassified_api_host_is_named_as_such():
    from agent.lib import shapes
    v, reasons = shapes.verdict(
        attributed=0,
        residue={"pathLiterals": [], "sinks": [{"loc": "src/Client.php:97"}]},
        coverage={"php": ["sink", "url"]},
        unclassified_api_hosts=1)
    assert v == "UNKNOWN"
    assert "uncatalogued-vendor" in reasons, \
        "a detected-but-unnamed API host must say so, not hide behind sdk-only-no-callsite"


def test_uncatalogued_beats_the_sink_reason_when_a_host_was_actually_found():
    """Both conditions hold for that repo — 0 attributed, sinks present, one Unknown API host.
    The sink reason says 'we cannot see the destination'; here we CAN see it, we just have no
    name for it. The more specific, actionable reason must win."""
    from agent.lib import shapes
    _, reasons = shapes.verdict(
        attributed=0, residue={"pathLiterals": [], "sinks": [{"loc": "a.php:9"}]},
        coverage={"php": ["sink"]}, unclassified_api_hosts=2)
    assert "uncatalogued-vendor" in reasons
    assert "sdk-only-no-callsite" not in reasons


def test_no_unclassified_hosts_keeps_the_old_reasons():
    """A repo that genuinely resolved nothing still reports the original blindness."""
    from agent.lib import shapes
    _, reasons = shapes.verdict(
        attributed=0, residue={"pathLiterals": [], "sinks": [{"loc": "a.php:9"}]},
        coverage={"php": ["sink"]}, unclassified_api_hosts=0)
    assert "sdk-only-no-callsite" in reasons
    assert "uncatalogued-vendor" not in reasons

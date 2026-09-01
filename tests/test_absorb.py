from types import SimpleNamespace

import pytest
import yaml

from agent import absorb


def test_verbatim_date_check_accepts_common_human_forms():
    """The verbatim-date gate: a retirement date must appear ON the cited page, in whatever human
    form the vendor wrote it — so the model can't slip in a date it merely inferred."""
    d = "2026-02-03"
    for text in ("...ceases to work on 2026-02-03.",
                 "Sunset date: February 3, 2026 — migrate before then.",
                 "retires on Feb 3, 2026",
                 "the endpoint will be removed 3 February 2026",
                 "effective 02/03/2026 (US format)",
                 "on February 3rd, 2026 the legacy embed stops working"):
        assert absorb.date_in_text(d, text), text


def test_verbatim_date_check_rejects_absent_or_wrong_date():
    assert not absorb.date_in_text("2026-02-03", "the API is being deprecated soon")   # no date at all
    assert not absorb.date_in_text("2026-02-03", "retires February 4, 2026")            # a DIFFERENT date
    assert not absorb.date_in_text("2026-02-03", "")                                    # no excerpt
    assert not absorb.date_in_text("not-a-date", "February 3, 2026")                    # unparseable claim


def test_verbatim_date_check_requires_a_token_boundary_not_a_bare_substring():
    """The date must appear AS a date in the text, not merely as a substring of some larger
    unrelated token — a build id, a longer digit run, etc."""
    # "2026-11-30" is a substring of "12026-11-3012" but is not itself present as a date.
    assert not absorb.date_in_text("2026-11-30", "build id 12026-11-3012")
    # the compact ISO form ("20261130") parses fine via date.fromisoformat, and its
    # human-readable forms are legitimately derived from it — but the compact form itself must
    # not match as a substring of a larger token either.
    assert not absorb.date_in_text("20261130", "build 20261130x failed")
    # sanity: the same date at a real boundary still matches.
    assert absorb.date_in_text("2026-11-30", "GeoMapper API v1 retires 2026-11-30.")


# --- check 1: a date nobody sourced is not admissible ---------------------------

def test_sunset_without_a_source_url_is_rejected():
    bad = [{"vendor": "eBay", "operation": "GetX", "retires": "2026-01-01"}]
    problems = absorb.check_sunsets(bad)
    assert any("no source URL" in p for p in problems)


def test_sunset_with_an_unparseable_date_is_rejected():
    bad = [{"vendor": "eBay", "operation": "GetX", "retires": "sometime in 2026",
            "source": "https://developer.ebay.com/x"}]
    assert any("YYYY-MM-DD" in p for p in absorb.check_sunsets(bad))


def test_a_properly_sourced_and_dated_sunset_passes():
    ok = [{"vendor": "eBay", "operation": "GetCategories", "retires": "2026-04-15",
           "source": "https://developer.ebay.com/develop/get-started/api-deprecation-status"}]
    assert absorb.check_sunsets(ok) == []


def test_sunset_without_a_scope_is_rejected():
    bad = [{"vendor": "eBay", "retires": "2026-04-15", "source": "https://x/y"}]
    assert any("needs a scope" in p for p in absorb.check_sunsets(bad))


# --- check 2/3: the idiom must deliver its claims and invent nothing -------------

_EP = lambda vendor, files: {"vendor": vendor, "files": files}


def _scanner(before, after):
    return lambda insts: after if insts else before


def test_idiom_that_does_not_attribute_its_claimed_call_sites_is_rejected():
    scan = _scanner(
        before={"endpoints": [], "residue": {"pathLiterals": [{"loc": "a.php:3"}]}},
        after={"endpoints": [], "residue": {"pathLiterals": [{"loc": "a.php:3"}]}})
    problems = absorb.verify_against_repo("/repo", [{"id": "x"}], ["a.php:3"], scan=scan)
    assert any("still unattributed" in p for p in problems)


def test_idiom_that_invents_a_new_vendor_is_rejected():
    """The cardinal rule: no false endpoints. Closing a gap by inventing calls
    elsewhere is worse than the gap."""
    scan = _scanner(
        before={"endpoints": [_EP("eBay", ["a.php:3"])], "residue": {"pathLiterals": []}},
        after={"endpoints": [_EP("eBay", ["a.php:3"]), _EP("Stripe", ["z.php:9"])],
               "residue": {"pathLiterals": []}})
    problems = absorb.verify_against_repo("/repo", [{"id": "x"}], ["a.php:3"], scan=scan)
    assert any("not previously present" in p and "Stripe" in p for p in problems)


def test_idiom_that_grows_residue_is_rejected():
    scan = _scanner(
        before={"endpoints": [_EP("eBay", ["a.php:3"])],
                "residue": {"pathLiterals": [{"loc": "b.php:1"}]}},
        after={"endpoints": [_EP("eBay", ["a.php:3"])],
               "residue": {"pathLiterals": [{"loc": "b.php:1"}, {"loc": "c.php:2"}]}})
    assert any("residue grew" in p for p in
               absorb.verify_against_repo("/repo", [{"id": "x"}], ["a.php:3"], scan=scan))


def test_a_good_idiom_passes_all_three_checks():
    scan = _scanner(
        before={"endpoints": [_EP("eBay", ["a.php:3"])],
                "residue": {"pathLiterals": [{"loc": "b.php:1"}]}},
        after={"endpoints": [_EP("eBay", ["a.php:3", "b.php:1"])],
               "residue": {"pathLiterals": []}})          # gap closed, nothing invented
    assert absorb.verify_against_repo("/repo", [{"id": "x"}], ["b.php:1"], scan=scan) == []


def test_malformed_idiom_instances_are_rejected_before_any_scan():
    assert absorb.check_idioms([{"id": "x", "family": "telepathy", "evidence": "a:1"}])
    assert absorb.check_idioms([{"id": "x", "family": "url-assembly"}])      # no evidence/base
    assert absorb.check_idioms([{"id": "ok", "family": "url-assembly",
                                 "base": "$A->x()", "evidence": "r f.php:1"}]) == []


def test_absorb_attestation_is_honored_by_a_later_scan(tmp_path, monkeypatch):
    """The Learn loop's core promise: after absorb resolves a repo's blindness, the NEXT scan
    of that same repo sees the attestation and stops calling it UNKNOWN. This was broken —
    _cmd_absorb wrote the attestation under a bare-name key ("svc@fp") while
    inventory_scan._shape_of looks it up with the repo's abspath ("svc:<hash>@fp"), so the two
    never matched and absorb never 'stuck'. This test fails on that bug and passes once
    _cmd_absorb keys the attestation the same way the scanner reads it."""
    from agent import cli
    from agent.lib import shapes
    import agent.lib.engine as engine_mod
    import agent.lib.endpoints as endpoints_mod

    repo = tmp_path / "svc"; repo.mkdir()
    state = tmp_path / "state"; state.mkdir()
    staged = tmp_path / "absorb-staged"; staged.mkdir()
    (staged / "idioms.yaml").write_text(yaml.safe_dump(
        [{"id": "svc-base", "family": "url-assembly", "base": "$A->baseUrl",
          "evidence": "svc f.php:1"}]))
    overlay = tmp_path / "overlay"; overlay.mkdir()          # promote here, not the real catalogs
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(overlay))

    # a repo the gate accepts unchanged (no claims): one attributed endpoint + one opaque sink
    fake = {"endpoints": [{"vendor": "eBay", "files": ["f.php:1"]}],
            "residue": {"pathLiterals": [], "sinks": [{"kind": "curl_exec", "loc": "g.php:4"}]}}
    monkeypatch.setattr(cli.scan_util, "resolve_engine", lambda: "fake")
    monkeypatch.setattr(engine_mod, "run_scan", lambda *a, **k: {"matches": []})
    monkeypatch.setattr(endpoints_mod, "scan_endpoints", lambda *a, **k: fake)

    args = SimpleNamespace(staged=str(staged), repo=str(repo), state=str(state),
                           repo_name=None, now="2026-07-27")
    assert cli._cmd_absorb(args) == 0                        # gate passed, attestation written

    fp = shapes.residue_fingerprint(fake["residue"])
    at = shapes.load_attestations(str(state))
    # the scanner will look it up with the repo's abspath — the attestation must match THAT key
    assert shapes.is_attested(at, "svc", fp, repo_abs=str(repo))


def test_promote_appends_staged_specs(tmp_path):
    staged = tmp_path / "staged"; staged.mkdir()
    (staged / "idioms.yaml").write_text(yaml.safe_dump(
        [{"id": "new-one", "family": "url-assembly", "base": "$A->baseUrl",
          "evidence": "repo f.php:1"}]))
    idioms_f = tmp_path / "idioms.yaml"; idioms_f.write_text("- id: existing\n")
    sunsets_f = tmp_path / "sunsets.yaml"; sunsets_f.write_text("- vendor: x\n")
    added = absorb.promote(str(staged), idioms_path=str(idioms_f), sunsets_path=str(sunsets_f))
    assert added["idioms"] == 1 and added["sunsets"] == 0
    assert "new-one" in idioms_f.read_text() and "existing" in idioms_f.read_text()


def test_measure_reports_the_attributed_delta_and_claims():
    scan = _scanner(
        before={"endpoints": [_EP("eBay", ["a.php:3"])],
                "residue": {"pathLiterals": [{"loc": "b.php:1"}, {"loc": "c.php:2"}]}},
        after={"endpoints": [_EP("eBay", ["a.php:3", "b.php:1"])],
               "residue": {"pathLiterals": [{"loc": "c.php:2"}]}})
    m = absorb.measure_against_repo("/repo", [{"id": "x"}], ["b.php:1"], scan=scan)
    assert m["attributedBefore"] == 1 and m["attributedAfter"] == 2      # +1 traced call
    assert m["residueBefore"] == 2 and m["residueAfter"] == 1            # -1 residue
    assert m["claims"] == {"met": ["b.php:1"], "missing": []}
    assert m["problems"] == []                                          # would pass


def test_absorb_check_measures_but_writes_nothing(tmp_path, monkeypatch):
    """--check is the iteration instrument: report the delta, write NOTHING. Proven against its
    bug — a PASSING proposal under --check must leave the overlay AND the attestation untouched
    (the loop must be free to probe without committing)."""
    from agent import cli
    from agent.lib import shapes
    import agent.lib.engine as engine_mod
    import agent.lib.endpoints as endpoints_mod

    repo = tmp_path / "svc"; repo.mkdir()
    state = tmp_path / "state"; state.mkdir()
    staged = tmp_path / "absorb-staged"; staged.mkdir()
    (staged / "idioms.yaml").write_text(yaml.safe_dump(
        [{"id": "svc-base", "family": "url-assembly", "base": "$A->baseUrl()", "evidence": "svc f.php:1"}]))
    (staged / "claims.yaml").write_text(yaml.safe_dump(["f.php:1"]))
    overlay = tmp_path / "overlay"; overlay.mkdir()
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(overlay))

    before = {"endpoints": [{"vendor": "eBay", "files": ["x.php:9"]}],
              "residue": {"pathLiterals": [{"loc": "f.php:1"}]}}
    after = {"endpoints": [{"vendor": "eBay", "files": ["x.php:9", "f.php:1"]}],
             "residue": {"pathLiterals": []}}
    calls = {"n": 0}
    def fake(*a, **k):                          # scan(None)=before (1st), scan(idioms)=after (2nd)
        calls["n"] += 1
        return before if calls["n"] % 2 == 1 else after
    monkeypatch.setattr(cli.scan_util, "resolve_engine", lambda: "fake")
    monkeypatch.setattr(engine_mod, "run_scan", lambda *a, **k: {"matches": []})
    monkeypatch.setattr(endpoints_mod, "scan_endpoints", fake)

    args = SimpleNamespace(staged=str(staged), repo=str(repo), state=str(state),
                           repo_name=None, now="2026-07-28", check=True)
    assert cli._cmd_absorb(args) == 0                        # a passing proposal
    assert shapes.load_attestations(str(state)) == {}       # NO attestation written
    assert not (overlay / "idioms.local.yaml").exists()     # NO overlay promotion


# --- path-constant: a config-injected wrapper's BOUND vendor is the reviewed claim ----------

def test_path_constant_bound_vendor_is_not_treated_as_invented():
    """A path-constant instance introduces its bound vendor by design (a config-injected host
    classified nothing before). That vendor is the REVIEWED binding, not an invented call —
    the gate must allow it while every OTHER new-vendor stays forbidden."""
    staged = [{"id": "catch-api-paths", "family": "path-constant", "repo": "example-org/catchapi",
               "vendor": "Catch", "pathRegex": r"^/api/", "evidence": "src/CatchApi/GetOrders.php:9"}]
    scan = _scanner(
        before={"endpoints": [], "residue": {"pathLiterals": [], "pathConstants": []}},
        after={"endpoints": [_EP("Catch", ["src/CatchApi/GetOrders.php:9"])],
               "residue": {"pathLiterals": [], "pathConstants": []}})
    problems = absorb.verify_against_repo("/repo", staged, ["src/CatchApi/GetOrders.php:9"], scan=scan)
    assert problems == []


def test_path_constant_that_sweeps_unclaimed_sites_is_rejected():
    """The guard against the bug: an over-broad pathRegex (^/ ) sweeps constants the reviewer
    never named. Even for a bound vendor, an unclaimed site fails the gate."""
    staged = [{"id": "catch-broad", "family": "path-constant", "repo": "example-org/catchapi",
               "vendor": "Catch", "pathRegex": r"^/", "evidence": "a.php:9"}]
    scan = _scanner(
        before={"endpoints": [], "residue": {"pathLiterals": [], "pathConstants": []}},
        after={"endpoints": [_EP("Catch", ["a.php:9", "b.php:2"])],
               "residue": {"pathLiterals": [], "pathConstants": []}})
    problems = absorb.verify_against_repo("/repo", staged, ["a.php:9"], scan=scan)
    assert any("did not claim" in p and "b.php:2" in p for p in problems)


def test_path_constant_that_grows_pathconstant_residue_is_rejected():
    """Surfacing a path constant the instance cannot attribute is a net-new blind spot —
    residue.pathConstants counts toward the residue-must-shrink guard."""
    staged = [{"id": "catch-api-paths", "family": "path-constant", "repo": "example-org/catchapi",
               "vendor": "Catch", "pathRegex": r"^/api/", "evidence": "a.php:9"}]
    scan = _scanner(
        before={"endpoints": [], "residue": {"pathLiterals": [], "pathConstants": []}},
        after={"endpoints": [_EP("Catch", ["a.php:9"])],
               "residue": {"pathLiterals": [], "pathConstants": [{"loc": "b.php:2"}]}})
    assert any("residue grew" in p for p in
               absorb.verify_against_repo("/repo", staged, ["a.php:9"], scan=scan))


def test_a_claim_outside_the_scanners_own_blind_spots_is_refused():
    """REGRESSION — the guard existed but was never wired in. `check_claims_in_scope` says of
    itself "Weakening this check is a P0 regression", and it had ZERO callers: not the gate,
    not measure_against_repo, not the CLI. The rule lived only as prose in the promptfile,
    which the docstring itself says nobody enforces in an autonomous loop.

    The attack it stops: `unclaimed` proves every ATTRIBUTED site was named, which is only
    meaningful if the claims were written first. An agent can instead scan, read whatever an
    over-broad pattern swept up, and then write claims.yaml to match — every attributed site is
    "claimed", the gate passes, and nobody approved the rule. Bounding claims to the blind spots
    the certified scan flagged BEFORE any agent saw the code caps what a gamed file can cover.

    Here b.php:2 was attributed and duly claimed, but the pre-change scan never called it a
    blind spot — so it is expansion beyond the stated job.

    Uses `url-assembly` deliberately: `path-constant` is exempt from this check because no
    path-constant rule exists until an instance is staged, so its sites CANNOT appear in a
    pre-change scan (see the reason in measure_against_repo)."""
    staged = [{"id": "broad-base", "family": "url-assembly", "repo": "example-org/catchapi",
               "base": "$this->host", "evidence": "a.php:9"}]
    scan = _scanner(
        before={"endpoints": [_EP("Catch", [])],
                "residue": {"pathLiterals": [{"loc": "a.php:9"}], "pathConstants": []}},
        after={"endpoints": [_EP("Catch", ["a.php:9", "b.php:2"])],
               "residue": {"pathLiterals": [], "pathConstants": []}})
    problems = absorb.verify_against_repo("/repo", staged, ["a.php:9", "b.php:2"], scan=scan)
    assert any("out of scope" in p and "b.php:2" in p for p in problems), problems


def test_a_claim_on_a_sink_the_brief_flagged_is_in_scope():
    """The scope is every blind spot the brief enumerates — versioned path literals AND egress
    sinks AND path constants. Bounding it to path literals alone would refuse the legitimate
    case the operation-marker family exists for: a sink whose URL is assembled out of reach."""
    staged = [{"id": "x-marker", "family": "operation-marker", "repo": "example-org/api",
               "vendor": "Catch", "marker": "GetOrders", "evidence": "a.php:9"}]
    scan = _scanner(
        before={"endpoints": [_EP("Catch", [])],
                "residue": {"pathLiterals": [], "pathConstants": [], "sinks": [{"loc": "a.php:9"}]}},
        after={"endpoints": [_EP("Catch", ["a.php:9"])],
               "residue": {"pathLiterals": [], "pathConstants": [], "sinks": []}})
    problems = absorb.verify_against_repo("/repo", staged, ["a.php:9"], scan=scan)
    assert not any("out of scope" in p for p in problems), problems


def test_verbatim_date_check_accepts_a_two_digit_year():
    """Vendors write two-digit years, and the gate could not see them.

    Groq's own deprecation table publishes `Shutdown Date: 08/16/26` — a date already PAST as of
    2026-09-01. Every form the check knew carried a four-digit year, so a real, sourced,
    past-due sunset could not be absorbed: the gate refused it as "the date is not on the page"
    when the date was plainly on the page. A guard that cannot read the vendor's own notation
    silently protects nothing and blocks real findings.
    """
    d = "2026-08-16"
    for text in ("Shutdown Date: 08/16/26",
                 "shuts down 8/16/26",
                 "retires 16/08/26 (EU format)"):
        assert absorb.date_in_text(d, text), text


def test_a_two_digit_year_still_needs_the_right_day_and_month():
    assert not absorb.date_in_text("2026-08-16", "Shutdown Date: 08/17/26")
    assert not absorb.date_in_text("2026-08-16", "Shutdown Date: 08/16/25")


def test_two_digit_years_are_only_offered_this_century():
    """`26` means 2026 here. Emitting the same short form for 1926 would let a page about a
    century-old date satisfy a claim about a modern one — the check would stop distinguishing
    the two. Outside 2000-2099 the four-digit forms are the only ones accepted."""
    assert not absorb.date_in_text("1926-08-16", "Shutdown Date: 08/16/26")
    assert absorb.date_in_text("1926-08-16", "Shutdown Date: 08/16/1926")


def test_a_two_digit_year_still_needs_a_token_boundary():
    """The same rule as every other form: a short date is easier to hit inside a version string
    or a build id, so the boundary matters MORE here, not less."""
    assert not absorb.date_in_text("2026-08-16", "version 108/16/265")
    assert not absorb.date_in_text("2026-08-16", "8/16/260")

"""Regressions from the deliberate self-audit (2026-07-20).

Every test here corresponds to a bug that was FOUND AND REPRODUCED in the shipped
tool. They share one theme: the scanner must never look more confident than its
evidence — neither by losing evidence silently, nor by claiming more than it saw.
"""
import tempfile
from pathlib import Path

from agent import absorb
from agent.lib import shapes
from agent.lib.endpoints import scan_endpoints
from agent.lib.engine import run_scan
from agent.lib.vendors import Vendor

_EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
_STRIPE = Vendor("Stripe", "api:stripe", ("stripe.com",), r"/(v[0-9]+)")
_KINDS = {"php": ["sink", "path-assembly", "url"]}


def test_malformed_engine_output_is_an_error_not_a_clean_scan():
    """A crash mid-write or a stray warning line before the JSON must not read as
    'scanned, found nothing' — that is indistinguishable from a clean repo."""
    res = run_scan("/repo", "/nope.yaml", run=lambda a: "WARNING: oom\n{truncated")
    assert res["errors"], "a parse failure must surface, not vanish"
    assert "not valid JSON" in res["errors"][0]["message"]


def test_multiline_literal_is_read_from_matched_text_not_the_start_line(tmp_path):
    """A heredoc carries its URL past the node's first line; reading only that line
    lost it from endpoints AND residue."""
    (tmp_path / "h.php").write_text("x")
    out = scan_endpoints([{"kind": "url", "path": "h.php", "line": 2,
                           "text": "<<<EOT\nhttps://api.stripe.com/v1/charges\nEOT"}],
                         str(tmp_path), [_STRIPE])
    assert [e["domain"] for e in out["endpoints"]] == ["api.stripe.com"]


def test_a_repo_of_unmodeled_languages_cannot_report_known(tmp_path):
    """Kotlin/Rust/Swift are not in the extension map, so the census was empty and the
    coverage loop had nothing to iterate — reporting KNOWN for a repo we cannot read."""
    (tmp_path / "Main.kt").write_text('val u = "https://api.stripe.com/v1/x"')
    sh = shapes.build(str(tmp_path), "kt", [], {"pathLiterals": [], "sinks": []}, _KINDS)
    assert sh["verdict"] == "UNKNOWN" and shapes.UNMODELED_LANGUAGE in sh["reasons"]


def test_a_repo_with_nothing_readable_reports_unknown(tmp_path):
    """DECISION REVERSED 2026-08-26. This test previously asserted the opposite — a README-only
    repo was KNOWN, on the reasoning that "the fix must not turn 'nothing to miss' into a false
    alarm". That reasoning holds for a genuine docs repo and fails for the case that turned up on
    a real fleet: many projects keep a README on their default branch and their code on `dev`, so
    an empty scan means WE READ THE WRONG BRANCH, not that there is nothing to miss.

    The scanner cannot tell those two apart from content — which is exactly why it must not
    assert the flattering one. KNOWN over a repo we could not read is principle 1 inverted, and
    it is how a blind scan reaches a reader looking like a clean one.

    Accepted cost, recorded here so nobody rediscovers it as a bug: a genuine docs or runbooks
    repo is now permanently UNKNOWN. Quieting that needs an acknowledged-empty attestation, with
    an approver and an expiry like every other disposition in this codebase; it is deliberately
    not invented here. See docs/superpowers/specs/2026-08-26-explicit-branch-design.md."""
    (tmp_path / "README.md").write_text("# docs")
    sh = shapes.build(str(tmp_path), "docs", [], {"pathLiterals": [], "sinks": []}, _KINDS)
    assert sh["verdict"] == "UNKNOWN"
    assert sh["reasons"] == [shapes.NO_READABLE_SOURCE]


def test_orphan_operation_markers_become_residue_not_nothing(tmp_path):
    """With 2 classified vendors the attribution guard correctly declines — but the
    marker is still evidence of an API call and must not disappear."""
    (tmp_path / "cfg.php").write_text("$a='https://api.ebay.com'; $b='https://api.stripe.com';")
    out = scan_endpoints([{"kind": "url", "path": "cfg.php", "line": 1},
                          {"kind": "operation-marker", "path": "w.php", "line": 1,
                           "text": "'<GetWeatherRequest>'"}], str(tmp_path), [_EBAY, _STRIPE])
    assert not any(e.get("operation") for e in out["endpoints"])       # not attributed
    assert out["residue"]["operations"] == [{"operation": "GetWeather", "loc": "w.php:1"}]


def test_inferred_attribution_is_labelled_distinctly_from_observed(tmp_path):
    """Single-vendor attribution is a guess about the REPO, not evidence from the LINE.
    A reader must be able to tell which is which."""
    (tmp_path / "cfg.php").write_text("$h='https://api.ebay.com';")
    (tmp_path / "op.php").write_text("x")
    out = scan_endpoints([{"kind": "url", "path": "cfg.php", "line": 1},
                          {"kind": "operation-marker", "path": "op.php", "line": 1,
                           "text": "'<GetOrdersRequest>'"}], str(tmp_path), [_EBAY])
    by = {e.get("operation") or e["domain"]: e["attribution"] for e in out["endpoints"]}
    assert by["api.ebay.com"] == "observed"      # the host was read at that line
    assert by["GetOrders"] == "inferred"         # the vendor was assumed from the repo


def test_gate_rejects_a_proposal_that_attributes_beyond_its_claim():
    """An over-broad pattern sweeps up call-sites nobody reviewed. Every attributed
    site must be named in the claim."""
    before = {"endpoints": [{"vendor": "Amazon SP-API", "files": ["real.php:1"]}],
              "residue": {"pathLiterals": [{"loc": "a.php:7"}, {"loc": "b.php:3"}]}}
    after = {"endpoints": [{"vendor": "Amazon SP-API",
                            "files": ["real.php:1", "a.php:7", "b.php:3"]}],
             "residue": {"pathLiterals": []}}
    problems = absorb.verify_against_repo("/r", [{"id": "x"}], ["a.php:7"],
                                          scan=lambda i: after if i else before)
    assert any("did not claim" in p and "b.php:3" in p for p in problems)


def test_attestation_cannot_bleed_between_two_repos_of_the_same_name(tmp_path):
    """`svc` is a common basename; two unrelated repos with identical residue shared an
    attestation key, so reviewing one silently cleared the other."""
    residue = {"pathLiterals": [{"sample": "/v2/checkout", "loc": "gw.php:3"}], "sinks": []}
    fp = shapes.residue_fingerprint(residue)
    shapes.attest(str(tmp_path), "svc", fp, resolved_by="A", date="2026-07-20",
                  repo_abs="/orgA/svc")
    at = shapes.load_attestations(str(tmp_path))
    assert shapes.is_attested(at, "svc", fp, "/orgA/svc")          # the reviewed one
    assert not shapes.is_attested(at, "svc", fp, "/orgB/svc")      # never reviewed


def test_grade_cannot_contradict_the_verdict():
    """A Go-only repo produces no residue, so the grade said HIGH while the verdict
    said UNKNOWN(no-egress-signal), in the same document."""
    from agent.inventory_scan import _coverage_grade
    assert _coverage_grade(attributed=0, unattributed_paths=0, sinks=0,
                           verdict="UNKNOWN") == "PARTIAL"
    assert _coverage_grade(attributed=5, unattributed_paths=0, sinks=0,
                           verdict="KNOWN") == "HIGH"


def _sunset(repo, op, date, rec, files):
    return {"repo": repo, "ref": "eBay", "kind": "sunset", "severity": "SUNSET",
            "status": "DEPRECATED", "operation": op, "date": date, "domain": None,
            "version": None, "recommendation": rec, "files": files,
            "first_seen": "2026-07-20"}


def test_sunset_actions_are_per_operation_not_per_vendor():
    """Twelve dead eBay calls must not collapse into one action labelled "eBay".

    A vendor is not a job. GetCategoryFeatures migrates to the Metadata API by
    2026-06-04; AddDispute migrated to Post-Order by 2023-01-27. Different work,
    different deadlines, different owners. Grouping sunsets on (repo, ref) rendered
    the dashboard tile as `Sunsets 1` while the audit held twelve findings — the
    operation axis was present in the data and discarded at the last step.
    """
    from agent.lib.actions import build_actions
    findings = [
        _sunset("ebayapi", "GetCategoryFeatures", "2026-06-04",
                "migrate to Metadata API", ["src/Ebay/EbayCategoryFieldsFeature.php:72"]),
        _sunset("ebayapi", "GetCategories", "2026-04-15",
                "migrate to Metadata API", ["src/Ebay/EbayCategoryFieldsFeature.php:18"]),
        _sunset("ebayapi", "AddDispute", "2023-01-27",
                "migrate to Post-Order API", ["src/Ebay/EbayOrderCancel.php:17"]),
    ]
    actions = build_actions(findings)
    assert len(actions) == 3, f"expected one action per operation, got {len(actions)}"
    assert {a["unit"] for a in actions} == {
        "GetCategoryFeatures", "GetCategories", "AddDispute"}
    # each must keep its OWN migration advice — the collapse also lost these
    by_unit = {a["unit"]: a for a in actions}
    assert by_unit["AddDispute"]["recommendation"] == "migrate to Post-Order API"
    assert by_unit["GetCategories"]["recommendation"] == "migrate to Metadata API"


def test_cve_actions_still_group_by_package():
    """The regrouping must NOT split CVEs: 30 CVEs against one package is still one
    upgrade, which is the whole reason actions exist."""
    from agent.lib.actions import build_actions
    findings = [
        {"repo": "app", "ref": "composer/guzzlehttp/guzzle", "kind": "cve",
         "severity": "HIGH", "status": "DEPRECATED", "version": "6.0.0", "fixed": "7.4.5",
         "recommendation": "upgrade", "files": ["composer.json"], "first_seen": "2026-07-20"},
        {"repo": "app", "ref": "composer/guzzlehttp/guzzle", "kind": "cve",
         "severity": "CRITICAL", "status": "DEPRECATED", "version": "6.0.0", "fixed": "7.4.5",
         "recommendation": "upgrade", "files": ["composer.json"], "first_seen": "2026-07-20"},
    ]
    actions = build_actions(findings)
    assert len(actions) == 1
    assert actions[0]["finding_count"] == 2
    assert actions[0]["unit"] is None


def test_sunsets_without_an_operation_group_by_host():
    """Host-scoped sunsets (eBay Finding/Shopping, LMS) have no operation; they must
    still separate by the host being retired rather than merging into one row."""
    from agent.lib.actions import build_actions
    findings = [
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "severity": "SUNSET",
         "status": "DEPRECATED", "operation": None, "domain": "svcs.ebay.com",
         "version": None, "date": "2025-02-05", "recommendation": "migrate to Browse API",
         "files": ["src/config/ebay.php:39"], "first_seen": "2026-07-20"},
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "severity": "SUNSET",
         "status": "DEPRECATED", "operation": None, "domain": "webservices.ebay.com",
         "version": None, "date": "2022-04-30", "recommendation": "migrate to Feed API",
         "files": ["src/Ebay/src/LMS/ServiceEndpointsAndTokens.php:9"],
         "first_seen": "2026-07-20"},
    ]
    actions = build_actions(findings)
    assert len(actions) == 2
    assert {a["unit"] for a in actions} == {"svcs.ebay.com", "webservices.ebay.com"}


def test_operation_survives_into_the_rendered_dashboard():
    """Assert through the RENDER, not just build_actions.

    The per-operation grouping was correct in build_actions and its unit test passed,
    while the dashboard still showed twelve rows labelled "eBay": _action_view
    whitelists action fields and silently dropped `unit`. A test one layer below the
    artifact the user reads cannot see that. This one reads the HTML.
    """
    from agent.lib.dashboard_render import render_dashboard
    findings = [
        _sunset("ebayapi", "GetCategoryFeatures", "2026-06-04",
                "migrate to Metadata API", ["src/Ebay/EbayCategoryFieldsFeature.php:72"]),
        _sunset("ebayapi", "AddDispute", "2023-01-27",
                "migrate to Post-Order API", ["src/Ebay/EbayOrderCancel.php:17"]),
    ]
    from agent.lib.actions import build_actions
    audit = {"generated": "2026-07-20", "findings": findings,
             "actions": build_actions(findings), "counts": {"reposAffected": 1}}
    inventory = {"repos": [{"path": "ebayapi", "endpoints": [], "sdks": []}],
                 "scope": {"reposScanned": 2}, "coverage": {}}
    html = render_dashboard(inventory, audit, "2026-07-20")
    assert "GetCategoryFeatures" in html, "the operation never reached the dashboard"
    assert "AddDispute" in html
    # and the header (now a reactive Vue binding, not server-built text) must not be fed a
    # count that implies only one repo was scanned — assert the numbers in the trust-anchor
    # blob the headline binds to (`{{ counts.reposAffected }} of {{ counts.reposScanned }}`)
    import json
    import re
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>', html, re.S)
    blob = json.loads(m.group(1).replace("\\u003c", "<"))
    assert blob["counts"]["reposAffected"] == 1 and blob["counts"]["reposScanned"] == 2


def test_gate_accepts_a_dateless_deprecation_only_when_declared():
    """The catalog permits dateless deprecations ("Omit if already deprecated with no
    fixed date") and the seed Amazon MWS entry has none — but the gate rejected every
    such entry, so no legitimate undated retirement could ever be absorbed.

    Silence is ambiguous: "the vendor set no date" and "I couldn't find the date" look
    the same, and only the first is admissible. The marker forces the author to say which.
    """
    from agent.absorb import check_sunsets
    src = "https://developer-docs.amazon.com/sp-api/docs/migrating-from-amazon-mws"

    declared = [{"vendor": "Amazon SP-API", "version": "v0",
                 "status": "deprecated-no-date", "source": src}]
    assert check_sunsets(declared) == []

    silent = [{"vendor": "Amazon SP-API", "version": "v0", "source": src}]
    assert any("deprecated-no-date" in p for p in check_sunsets(silent))

    # a real date still must parse, and a source is still mandatory
    assert any("YYYY-MM-DD" in p for p in check_sunsets(
        [{"vendor": "X", "version": "v1", "retires": "soon", "source": src}]))
    assert any("no source URL" in p for p in check_sunsets(
        [{"vendor": "X", "version": "v1", "retires": "2026-01-01"}]))


def test_walmart_sub_apis_are_scoped_apart_by_front_loaded_path():
    """Walmart front-loads the version (/v3/insights/refunds), so the scoping must
    distinguish sub-APIs — a retired /v3/insights/items/trending must fire while a live
    /v3/feeds stays silent, not collapse into one /v3 finding."""
    from agent.audit import audit_inventory
    doc = {"generated": "2026-07-21", "repos": [{"path": "wm", "sdks": [], "endpoints": [
        {"vendor": "Walmart", "domain": "marketplace.walmartapis.com", "version": "v3",
         "apiPath": "/v3/insights/items/trending", "classified": True,
         "files": ["a.php:1"], "file_count": 1},
        {"vendor": "Walmart", "domain": "marketplace.walmartapis.com", "version": "v3",
         "apiPath": "/v3/feeds", "classified": True, "files": ["a.php:2"], "file_count": 1},
    ]}]}
    audit = audit_inventory(doc, "2026-07-21",
                            http=lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    wm = {f["path"]: f for f in audit["findings"] if f.get("ref") == "Walmart"}
    assert "/v3/insights/items/trending" in wm            # the dead one fires
    assert wm["/v3/insights/items/trending"]["date"] == "2025-03-31"
    assert wm["/v3/insights/items/trending"]["status"] == "DEPRECATED"
    assert "/v3/feeds" not in wm                          # the live one stays silent


def test_recommendation_is_date_aware_past_vs_future():
    """The PM's report: 'plan migration before 2025-01-21' when that date is 18 months
    gone. A past retirement must read as already-gone; only a future one is a deadline."""
    from agent.audit import _sunset_recommendation
    now = "2026-07-21"
    # past date -> "already retired", never "before"
    past = _sunset_recommendation("the Metadata API", "2025-01-21", now)
    assert "already retired 2025-01-21" in past and "before" not in past
    # future date -> a real deadline
    future = _sunset_recommendation("the Metadata API", "2027-03-27", now)
    assert "before 2027-03-27" in future
    # today counts as past (retired as of today)
    assert "already retired" in _sunset_recommendation(None, "2026-07-21", now)
    # no date -> neither
    assert "no fixed retirement date" in _sunset_recommendation("X", None, now)


def test_past_sunset_findings_do_not_say_migrate_before_a_gone_date():
    """End to end: a repo calling an already-dead Amazon API must not be told to plan
    migration BEFORE a date in the past."""
    from agent.audit import audit_inventory
    doc = {"generated": "2026-07-21", "repos": [{"path": "r", "sdks": [], "endpoints": [
        {"vendor": "Amazon SP-API", "domain": "sellingpartnerapi-na.amazon.com",
         "version": "v0", "apiPath": "/fba/inbound/v0", "classified": True,
         "files": ["a.php:1"], "file_count": 1}]}]}
    audit = audit_inventory(doc, "2026-07-21",
                            http=lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    f = next(x for x in audit["findings"] if x.get("path") == "/fba/inbound/v0")
    assert "already retired" in f["recommendation"]
    assert "before 2025-01-21" not in f["recommendation"]     # the exact PM complaint


# ── evidence must not be discarded before anything can count it ──────────────────

def test_lifecycle_finding_keeps_every_call_site_not_the_first_six():
    """REGRESSION (2026-08-20): `files` was truncated to 6 inside audit, so the true
    call-site total was destroyed at the source — actions and every renderer downstream
    could only ever see 6. Capping for display is fine; capping the EVIDENCE is not,
    because nothing downstream can recover a number that was already thrown away."""
    from agent.audit import _lifecycle_findings
    eps = [{"vendor": "Shopify", "version": "2023-10",
            "files": [f"app/Shopify_{i}.php:{i}"]} for i in range(22)]
    repo = {"path": "example-org/inventory-app", "endpoints": eps}
    f = [x for x in _lifecycle_findings(repo, "2026-08-20") if x["ref"] == "Shopify"][0]
    assert f["date"] == "2024-10-16"          # retired, per the published Shopify rule
    assert len(f["files"]) == 22


def test_finding_detail_prose_stays_bounded_and_admits_what_it_omitted():
    """The `detail` string is prose a human reads — it must NOT list 22 paths. It caps,
    but says so, rather than trailing off as though six were all there were."""
    from agent.audit import _lifecycle_findings
    eps = [{"vendor": "Shopify", "version": "2023-10",
            "files": [f"app/Shopify_{i}.php:{i}"]} for i in range(22)]
    f = [x for x in _lifecycle_findings({"path": "r", "endpoints": eps}, "2026-08-20")
         if x["ref"] == "Shopify"][0]
    assert f["detail"].count("app/Shopify_") == 6
    assert "+16 more" in f["detail"]


# ── secret findings (gitleaks, Task 2's repo["secrets"]) ──────────────────────────

def _secret_repo(**secret_kwargs):
    secret = {"ruleId": "generic-api-key", "path": "config/feedvisor.php", "line": 5,
             "commit": "a1b2c3d", "fingerprint": "a1b2c3d:config/feedvisor.php:generic-api-key:5"}
    secret.update(secret_kwargs)
    return {"path": "acme-supplier-tools", "secrets": [secret], "endpoints": [], "sdks": []}


def test_secret_finding_shape_matches_other_finding_kinds():
    from agent.audit import _secret_findings
    out = _secret_findings(_secret_repo())
    assert len(out) == 1
    f = out[0]
    assert f["repo"] == "acme-supplier-tools"
    assert f["kind"] == "secret"
    assert f["ref"] == "generic-api-key"
    assert f["severity"] == "CRITICAL"
    assert f["status"] == "EXPOSED"
    assert f["date"] is None and f["source_url"] is None      # never invent either
    assert f["files"] == ["config/feedvisor.php:5"]
    assert "config/feedvisor.php:5" in f["detail"]


def test_a_repo_with_no_secrets_produces_no_secret_findings():
    from agent.audit import _secret_findings
    assert _secret_findings({"path": "clean-repo", "secrets": []}) == []


def test_a_repo_with_no_secrets_key_at_all_produces_no_secret_findings():
    """Older cached inventory.json from before this feature shipped has no "secrets" key —
    must degrade to zero findings, not KeyError."""
    from agent.audit import _secret_findings
    assert _secret_findings({"path": "old-scan-repo"}) == []

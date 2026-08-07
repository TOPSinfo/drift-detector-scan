from agent.lib import vendor_sunsets as vs
from agent.audit import audit_inventory


_NOOP = {"osv_query": lambda *a, **k: [], "eol_check": lambda *a, **k: None,
         "http": lambda *a, **k: {}}


def test_unquoted_date_coerced_to_str_stays_json_serializable(tmp_path):
    import json
    p = tmp_path / "s.yaml"
    p.write_text("- { vendor: Amazon SP-API, version: v0, retires: 2026-09-30, source: u }\n")  # unquoted!
    loaded = vs.load_sunsets(str(p))
    assert isinstance(loaded[0]["retires"], str) and loaded[0]["retires"] == "2026-09-30"
    out = audit_inventory(_doc("Amazon SP-API", "v0", ["a.js:1"]), "2026-07-15",
                          sunsets=loaded, **_NOOP)
    json.dumps(out)                                    # must not raise (was: date not serializable)


def test_scopeless_entry_raises_rather_than_vanishing(tmp_path):
    """An unscopeable entry used to be skipped in silence. That hid eight sourced Amazon
    retirements — the catalog looked clean because it had forgotten what it was taught,
    which is indistinguishable from having nothing to report."""
    import pytest
    p = tmp_path / "s.yaml"
    p.write_text("- { vendor: X, source: u }\n- { vendor: Y, version: v1, source: u }\n")
    with pytest.raises(vs.MalformedSunset) as e:
        vs.load_sunsets(str(p))
    assert "no scope" in str(e.value)


def test_path_scope_is_a_valid_scope(tmp_path):
    """`path` scopes an entry to one API family — the axis Amazon retires on."""
    p = tmp_path / "s.yaml"
    p.write_text('- { vendor: Amazon SP-API, path: /fba/inbound/v0, retires: "2025-01-21", source: u }\n')
    loaded = vs.load_sunsets(str(p))
    assert loaded[0]["path"] == "/fba/inbound/v0"


def test_catalog_loads_and_status():
    cat = vs.load_sunsets()
    assert any(s["vendor"] == "Amazon MWS" for s in cat)          # seeded entry
    assert vs.status_for("2020-01-01", "2026-07-15", confirmed=True) == "DEPRECATED"
    assert vs.status_for("2027-01-01", "2026-07-15", confirmed=True) == "REVIEW"
    assert vs.status_for(None, "2026-07-15", confirmed=True) == "DEPRECATED"     # deprecated, no date
    assert vs.status_for("2020-01-01", "2026-07-15", confirmed=False) == "REVIEW"  # unconfirmed


def _doc(vendor, version, files):
    return {"repos": [{"path": "svc", "endpoints": [
        {"vendor": vendor, "version": version, "files": files}]}]}


def test_exact_version_match_future_is_review_with_filelines():
    sun = [{"vendor": "Amazon SP-API", "version": "v0", "retires": "2026-09-30",
            "replacement": "v2", "source": "https://amzn/x"}]
    out = audit_inventory(_doc("Amazon SP-API", "v0", ["orders/client.js:1", "sync.js:4"]),
                          "2026-07-15", sunsets=sun, **_NOOP)
    f = next(x for x in out["findings"] if x["kind"] == "sunset")
    assert f["status"] == "REVIEW" and f["ref"] == "Amazon SP-API"
    assert f["files"] == ["orders/client.js:1", "sync.js:4"]       # the code-level differentiator
    assert "migrate to v2 before 2026-09-30" in f["recommendation"]
    assert f["source_url"] == "https://amzn/x"


def test_whole_api_star_matches_any_version_and_past_is_deprecated():
    sun = [{"vendor": "Amazon MWS", "version": "*", "retires": "2024-01-01", "source": "u"}]
    out = audit_inventory(_doc("Amazon MWS", "?", ["mws.php:9"]), "2026-07-15", sunsets=sun, **_NOOP)
    f = next(x for x in out["findings"] if x["kind"] == "sunset")
    assert f["status"] == "DEPRECATED" and "mws.php:9" in f["files"]


def test_unknown_version_is_review_verify():
    sun = [{"vendor": "Shopify", "version": "2023-01", "retires": "2020-01-01", "source": "u"}]
    out = audit_inventory(_doc("Shopify", "?", ["oauth.ts:19"]), "2026-07-15", sunsets=sun, **_NOOP)
    f = next(x for x in out["findings"] if x["kind"] == "sunset")
    assert f["status"] == "REVIEW" and "verify" in f["detail"]      # can't confirm they're on 2023-01


def test_non_matching_version_not_flagged():
    sun = [{"vendor": "Amazon SP-API", "version": "v0", "retires": "2026-09-30", "source": "u"}]
    out = audit_inventory(_doc("Amazon SP-API", "v3", ["x.js:1"]), "2026-07-15", sunsets=sun, **_NOOP)
    assert not any(x["kind"] == "sunset" for x in out["findings"])  # they're on v3, not v0


def _doc_hosts(vendor, endpoints):
    # endpoints: list of (domain, version, [files])
    return {"repos": [{"path": "svc", "endpoints": [
        {"vendor": vendor, "domain": d, "version": v, "files": f} for d, v, f in endpoints]}]}


def test_domain_scoped_entry_flags_only_the_matching_host():
    # eBay's dead Finding API (svcs.ebay.com) shares version "v1" with the LIVE OAuth/REST host
    # (api.ebay.com). A domain-scoped entry must flag only the dead host.
    sun = [{"vendor": "eBay", "domain": "svcs.ebay.com", "retires": "2025-02-05",
            "replacement": "Browse API", "source": "https://developer.ebay.com/x"}]
    doc = _doc_hosts("eBay", [
        ("svcs.ebay.com", "v1", ["src/Ebay/find.php:37"]),        # dead Finding API
        ("api.ebay.com", "v1", ["src/Ebay/oauth.php:6"])])        # live OAuth/REST — same version!
    out = audit_inventory(doc, "2026-07-15", sunsets=sun, **_NOOP)
    sunsets = [x for x in out["findings"] if x["kind"] == "sunset"]
    assert len(sunsets) == 1
    f = sunsets[0]
    assert f["status"] == "DEPRECATED"                            # past 2025-02-05, host-confirmed
    assert f["files"] == ["src/Ebay/find.php:37"]                 # ONLY the dead host's call-site
    assert "src/Ebay/oauth.php:6" not in f["files"]               # live host NOT flagged
    assert "svcs.ebay.com" in f["detail"]
    # 2025-02-05 is past now (2026-07-15) -> "already retired", not "before"
    assert "migrate to Browse API NOW — already retired 2025-02-05" in f["recommendation"]


def test_domain_scoped_entry_ignores_repo_without_that_host():
    sun = [{"vendor": "eBay", "domain": "svcs.ebay.com", "retires": "2025-02-05", "source": "u"}]
    doc = _doc_hosts("eBay", [("api.ebay.com", "v1", ["a.php:1"])])   # only the live host
    out = audit_inventory(doc, "2026-07-15", sunsets=sun, **_NOOP)
    assert not any(x["kind"] == "sunset" for x in out["findings"])    # nothing dead here


def test_two_domain_entries_same_vendor_are_distinct_findings():
    from agent.lib.findings_state import fingerprint
    sun = [{"vendor": "eBay", "domain": "svcs.ebay.com", "retires": "2025-02-05", "source": "u"},
           {"vendor": "eBay", "domain": "open.api.ebay.com", "retires": "2025-02-05", "source": "u"}]
    doc = _doc_hosts("eBay", [
        ("svcs.ebay.com", "v1", ["find.php:1"]),
        ("open.api.ebay.com", None, ["shop.php:2"])])
    out = audit_inventory(doc, "2026-07-15", sunsets=sun, **_NOOP)
    sunsets = [x for x in out["findings"] if x["kind"] == "sunset"]
    assert len(sunsets) == 2                                       # both hosts, not collapsed
    fps = {fingerprint(f) for f in sunsets}
    assert len(fps) == 2                                          # distinct fingerprints (no collision)


def test_loader_accepts_domain_only_entry_without_version(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("- { vendor: eBay, domain: svcs.ebay.com, retires: 2025-02-05, source: u }\n")
    loaded = vs.load_sunsets(str(p))
    assert len(loaded) == 1
    assert loaded[0]["domain"] == "svcs.ebay.com"
    assert loaded[0]["retires"] == "2025-02-05"                   # coerced to str


def test_real_catalog_has_accurate_ebay_finding_and_shopping_sunsets():
    cat = vs.load_sunsets()
    # DOMAIN-scoped eBay entries: whole hosts that are dead. Operation-scoped
    # entries live on the shared LIVE host and have their own dates, so they are
    # deliberately not covered by this assertion.
    ebay = [s for s in cat if s["vendor"] == "eBay"
            and s.get("domain") in ("svcs.ebay.com", "open.api.ebay.com")]
    domains = {s.get("domain") for s in ebay}
    assert "svcs.ebay.com" in domains          # Finding API
    assert "open.api.ebay.com" in domains      # Shopping API
    assert len(ebay) == 2
    for s in ebay:
        assert s["retires"] == "2025-02-05"    # the announced decommission date
        assert s.get("source")                 # every entry cites a source
        assert "api.ebay.com" != s.get("domain")   # never target the LIVE host


def test_no_more_than_two_entries_share_a_source_url():
    # genericness guard (#1 from the PM demo): a lazy shared citation (many APIs -> one index
    # page) regresses loudly. Distinct text-fragment URLs count as distinct sources.
    import collections
    from agent.lib import vendor_sunsets as vs
    cat = vs.load_sunsets()
    counts = collections.Counter(s.get("source") for s in cat if s.get("source"))
    offenders = {url: n for url, n in counts.items() if n > 2}
    assert not offenders, f"more than 2 sunset entries share a source URL: {offenders}"


def test_operation_scoped_entry_flags_only_that_operation():
    """One host, many operations: a dead call must not condemn a live one."""
    sun = [{"vendor": "eBay", "operation": "GetCategories", "retires": "2026-04-15",
            "replacement": "Taxonomy API", "source": "https://developer.ebay.com/x"}]
    doc = {"repos": [{"path": "ebayapi", "endpoints": [
        {"vendor": "eBay", "domain": "ebay.com", "version": None,
         "operation": "GetCategories", "files": ["Cat.php:18"]},
        {"vendor": "eBay", "domain": "ebay.com", "version": None,
         "operation": "GetItem", "files": ["Item.php:9"]},          # alive
    ]}]}
    out = audit_inventory(doc, "2026-07-20", sunsets=sun, **_NOOP)
    f = [x for x in out["findings"] if x["kind"] == "sunset"]
    assert len(f) == 1 and f[0]["operation"] == "GetCategories"
    assert f[0]["files"] == ["Cat.php:18"]                          # NOT Item.php
    assert f[0]["status"] == "DEPRECATED"                           # past due


def test_real_catalog_operation_entries_are_sourced_and_dated():
    cat = vs.load_sunsets()
    ops = [s for s in cat if s.get("operation")]
    assert ops, "the operation axis needs at least one curated entry"
    for s in ops:
        assert s.get("source", "").startswith("http")               # never an invented date
        assert len(str(s.get("retires", ""))) == 10                 # YYYY-MM-DD
    by_op = {s["operation"]: s for s in ops}
    # verified from eBay's API Deprecation Status table (snapshot 2026-05-13)
    assert by_op["GetCategoryFeatures"]["retires"] == "2026-06-04"
    assert by_op["GetCategories"]["retires"] == "2026-04-15"

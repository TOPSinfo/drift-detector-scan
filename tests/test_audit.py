from agent.audit import audit_inventory


_DOC = {
    "repos": [
        {"path": "svc-a",
         "runtimes": {"php": {"range": "^7.4"}},
         "frameworks": {"laravel/framework": {"ver": "^9.0"}},
         "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1"},
                  {"eco": "npm", "pkg": "left-pad", "ver": "1.0.0"}]},
        {"path": "svc-b",
         "runtimes": {"php": {"range": "^8.3"}},
         "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1"}]},   # same pkg -> deduped query
    ]
}


def _fake_osv(eco, name, version, *, http=None):
    if name == "axios":
        return [{"id": "GHSA-x", "cve": "CVE-1", "severity": "HIGH", "summary": "ssrf",
                 "fixed": "1.7.4", "url": "https://osv.dev/x"}]
    return []


def _fake_eol(product, version, now, *, http=None):
    table = {("php", "7.4"): "DEPRECATED", ("php", "8.3"): "OK", ("laravel/framework", "9.0"): "REVIEW"}
    st = table.get((product, version))
    if st is None:
        return None
    return {"product": product, "slug": product.split("/")[0], "cycle": version,
            "status": st, "eol_date": "2022-11-28" if st == "DEPRECATED" else "2027-01-01",
            "latest": "8.3.10", "source_url": f"https://endoflife.date/{product.split('/')[0]}"}


def test_audit_produces_classified_findings_with_sources():
    out = audit_inventory(_DOC, "2026-07-14", http=lambda *a, **k: {}, osv_query=_fake_osv, eol_check=_fake_eol)
    f = out["findings"]
    # axios HIGH cve -> DEPRECATED in both repos; php 7.4 EOL -> DEPRECATED; laravel 9 -> REVIEW
    cve = [x for x in f if x["kind"] == "cve"]
    assert all(x["status"] == "DEPRECATED" and x["source_url"] for x in cve)
    assert any(x["kind"] == "eol" and x["ref"] == "php" and x["status"] == "DEPRECATED" for x in f)
    assert any(x["kind"] == "eol" and x["ref"] == "laravel/framework" and x["status"] == "REVIEW" for x in f)
    # php 8.3 is OK -> no finding
    assert not any(x["ref"] == "php" and x["version"] == "^8.3" for x in f)
    assert out["counts"]["DEPRECATED"] >= 3 and out["counts"]["REVIEW"] >= 1


def test_audit_dedupes_osv_queries():
    calls = {"n": 0}

    def counting_osv(eco, name, version, *, http=None):
        calls["n"] += 1
        return []

    audit_inventory(_DOC, "2026-07-14", http=lambda *a, **k: {}, osv_query=counting_osv, eol_check=_fake_eol)
    # axios appears in two repos + left-pad once = 2 unique package keys
    assert calls["n"] == 2


def test_audit_degrades_gracefully_when_source_down():
    def boom(*a, **k):
        raise ConnectionError("no network")

    out = audit_inventory(_DOC, "2026-07-14", http=lambda *a, **k: {}, osv_query=boom, eol_check=boom)
    assert out["findings"] == []                       # nothing fabricated
    assert out["coverage"]["osvErrors"] == 1 and out["coverage"]["eolErrors"] == 1
    assert any("unreachable" in n for n in out["coverage"]["notes"])


def test_cve_deduped_within_repo():
    doc = {"repos": [{"path": "svc", "sdks": [
        {"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "file": "a/package.json"},
        {"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "file": "b/package.json"},  # same pkg, 2nd manifest
    ]}]}
    out = audit_inventory(doc, "2026-07-14", http=lambda *a, **k: {}, osv_query=_fake_osv, eol_check=_fake_eol)
    assert len([f for f in out["findings"] if f["kind"] == "cve"]) == 1   # not 2


def test_eol_finding_carries_structured_fixed_version():
    # the renderer must never parse "upgrade to 8.5.8" back out of prose
    def eol_check(product, floor_, now, **kw):
        return {"status": "DEPRECATED", "cycle": "7.4", "eol_date": "2022-11-28",
                "recommended": "8.5.8", "source_url": "https://endoflife.date/php"}

    doc = {"repos": [{"path": "r", "sdks": [], "runtimes": {"php": {"range": "^7.4"}}}]}
    out = audit_inventory(doc, "2026-07-14", http=lambda *a, **k: {},
                          osv_query=lambda *a, **k: [], eol_check=eol_check)
    eol_findings = [f for f in out["findings"] if f["kind"] == "eol"]
    assert len(eol_findings) == 1
    assert eol_findings[0]["fixed"] == "8.5.8"                       # structured
    assert eol_findings[0]["recommendation"] == "upgrade to 8.5.8"   # prose still there


def test_eol_finding_fixed_is_none_when_no_recommendation():
    def eol_check(product, floor_, now, **kw):
        return {"status": "DEPRECATED", "cycle": "7.4", "eol_date": "2022-11-28",
                "recommended": None, "source_url": "https://endoflife.date/php"}

    doc = {"repos": [{"path": "r", "sdks": [], "runtimes": {"php": {"range": "^7.4"}}}]}
    out = audit_inventory(doc, "2026-07-14", http=lambda *a, **k: {},
                          osv_query=lambda *a, **k: [], eol_check=eol_check)
    eol_findings = [f for f in out["findings"] if f["kind"] == "eol"]
    assert eol_findings[0]["fixed"] is None
    assert eol_findings[0]["recommendation"] == "upgrade to a supported release"

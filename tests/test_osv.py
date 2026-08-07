from agent.lib import osv


_AXIOS_VULN = {
    "id": "GHSA-3g43-6gmg-66jw",
    "aliases": ["CVE-2026-44495"],
    "summary": "axios SSRF and credential leak",
    "database_specific": {"severity": "HIGH"},
    "affected": [{"ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.7.4"}]}]}],
    "references": [{"type": "ADVISORY", "url": "https://github.com/advisories/GHSA-3g43-6gmg-66jw"}],
}


def _fake_http(url, *, method="GET", body=None, timeout=20):
    assert method == "POST" and "osv.dev" in url
    if body["package"]["name"] == "axios":
        return {"vulns": [_AXIOS_VULN]}
    return {"vulns": []}


def test_query_package_normalizes_vuln():
    vulns = osv.query_package("npm", "axios", "0.21.1", http=_fake_http)
    assert len(vulns) == 1
    v = vulns[0]
    assert v["id"] == "GHSA-3g43-6gmg-66jw"
    assert v["cve"] == "CVE-2026-44495"           # picked from aliases
    assert v["severity"] == "HIGH"
    assert v["fixed"] == "1.7.4"
    assert v["url"].startswith("https://github.com/advisories/")


def test_query_package_skips_unsupported_ecosystem_and_missing_version():
    assert osv.query_package("go", "x", "1.0", http=_fake_http) == []
    assert osv.query_package("npm", "axios", None, http=_fake_http) == []


def test_query_all_dedupes_by_key():
    calls = {"n": 0}

    def counting(url, *, method="GET", body=None, timeout=20):
        calls["n"] += 1
        return {"vulns": []}

    pkgs = [("npm", "react", "19.0.0"), ("npm", "react", "19.0.0"), ("npm", "react-dom", "19.0.0")]
    result = osv.query_all(pkgs, http=counting)
    assert calls["n"] == 2                          # react queried once despite two occurrences
    assert set(result.keys()) == {("npm", "react", "19.0.0"), ("npm", "react-dom", "19.0.0")}


def test_severity_from_cvss_vector_when_no_ghsa_label():
    # PyPI/Packagist-style advisory: CVSS vector only, no database_specific.severity
    vuln = {"id": "PYSEC-1", "aliases": ["CVE-9"], "summary": "rce",
            "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
            "affected": [{"package": {"ecosystem": "PyPI", "name": "victim"},
                          "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.0"}]}]}]}

    def http(url, *, method="GET", body=None, timeout=20):
        return {"vulns": [vuln]}

    v = osv.query_package("python", "victim", "1.0", http=http)[0]
    assert v["severity"] == "CRITICAL"      # 9.8 base score -> CRITICAL (was silently "RATED"/REVIEW)
    assert v["fixed"] == "2.0"


def test_fixed_version_ignores_other_packages_in_advisory():
    vuln = {"id": "GHSA-multi", "aliases": [], "summary": "x", "database_specific": {"severity": "HIGH"},
            "affected": [
                {"package": {"ecosystem": "PyPI", "name": "other"},
                 "ranges": [{"events": [{"introduced": "0"}, {"fixed": "99.0"}]}]},
                {"package": {"ecosystem": "npm", "name": "target"},
                 "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.7.4"}]}]},
            ]}

    def http(url, *, method="GET", body=None, timeout=20):
        return {"vulns": [vuln]}

    v = osv.query_package("npm", "target", "0.21.1", http=http)[0]
    assert v["fixed"] == "1.7.4"             # not "99.0" from the unrelated PyPI package

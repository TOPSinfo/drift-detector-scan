"""SARIF 2.1.0 — findings as GitHub-code-scanning results, with real file:line locations.
Deterministic, no network."""
import json

from agent.lib import sarif


def _audit():
    return {"findings": [
        {"repo": "team/web", "kind": "sunset", "ref": "eBay", "status": "DEPRECATED",
         "detail": "eBay GetCategoryFeatures decommissioned 2026-06-04",
         "recommendation": "migrate to the Metadata API", "date": "2026-06-04",
         "source_url": "https://developer.ebay.com/x",
         "files": [{"loc": "src/Ebay/EbayCategoryFieldsFeature.php:72"}]},
        {"repo": "team/web", "kind": "cve", "ref": "npm/axios", "status": "REVIEW",
         "detail": "CVE-2021-3749 in axios", "id": "CVE-2021-3749",
         "recommendation": "upgrade to >= 0.21.2", "files": []},
    ]}


def test_it_is_a_sarif_log():
    doc = sarif.build_sarif(_audit())
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["tool"]["driver"]["name"] == "Drift Detector"


def test_a_sunset_finding_becomes_an_error_result_at_its_call_site():
    doc = sarif.build_sarif(_audit())
    res = [r for r in doc["runs"][0]["results"] if r["ruleId"] == "drift-vendor-sunset"]
    assert len(res) == 1
    r = res[0]
    assert r["level"] == "error"                          # DEPRECATED -> error
    loc = r["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "team/web/src/Ebay/EbayCategoryFieldsFeature.php"
    assert loc["region"]["startLine"] == 72               # the exact retired-API call site
    assert "migrate to the Metadata API" in r["message"]["text"]


def test_review_maps_to_warning_and_rules_are_declared():
    doc = sarif.build_sarif(_audit())
    cve = next(r for r in doc["runs"][0]["results"] if r["ruleId"] == "drift-cve")
    assert cve["level"] == "warning"                      # REVIEW -> warning
    rule_ids = {r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]}
    assert {"drift-vendor-sunset", "drift-cve"} <= rule_ids


def test_output_is_byte_identical():
    a = json.dumps(sarif.build_sarif(_audit()), sort_keys=True)
    b = json.dumps(sarif.build_sarif(_audit()), sort_keys=True)
    assert a == b


def test_bare_string_call_sites_are_handled_too():
    """Real findings carry `files` as bare 'path:line' strings, not only {loc: ...} dicts."""
    audit = {"findings": [{"repo": "r", "kind": "sunset", "ref": "eBay", "status": "DEPRECATED",
                           "detail": "x", "files": ["src/A.php:10"]}]}
    doc = sarif.build_sarif(audit)
    loc = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "r/src/A.php" and loc["region"]["startLine"] == 10

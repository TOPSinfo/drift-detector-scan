"""The SBOM is a CycloneDX projection of the inventory + audit — deterministic, and a faithful
parts-list-plus-vulnerabilities (SBOM + VEX). Pure Python, no network."""
from agent.lib import sbom


def _inv(**over):
    base = {"repos": [
        {"path": "team/web",
         "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "resolved": "0.21.1"},
                  {"eco": "composer", "pkg": "laravel/framework", "ver": "^9.0", "resolved": "9.5.2"}],
         "runtimes": {"php": {"range": "8.1"}},
         "frameworks": {"laravel": {"ver": "9.5.2"}}},
        {"path": "team/api",
         "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "resolved": "0.21.1"}],
         "runtimes": {}, "frameworks": {}},
    ]}
    base.update(over)
    return base


def _audit(**over):
    base = {"findings": [
        {"kind": "cve", "ref": "npm/axios", "version": "0.21.1", "cve": "CVE-2021-3749",
         "id": "CVE-2021-3749", "severity": "HIGH", "fixed": "0.21.2",
         "source_url": "https://osv.dev/CVE-2021-3749", "recommendation": "upgrade to >= 0.21.2"},
    ]}
    base.update(over)
    return base


def test_it_is_a_cyclonedx_document():
    doc = sbom.build_sbom(_inv(), _audit(), "2026-07-27")
    assert doc["bomFormat"] == "CycloneDX" and doc["specVersion"] == "1.5"
    assert doc["metadata"]["timestamp"] == "2026-07-27T00:00:00Z"
    # no random serialNumber — that would break byte-identical output
    assert "serialNumber" not in doc


def test_a_shared_library_is_one_component_recording_both_repos():
    doc = sbom.build_sbom(_inv(), _audit(), "2026-07-27")
    axios = [c for c in doc["components"] if c["name"] == "axios"]
    assert len(axios) == 1                                  # used in 2 repos -> ONE component
    assert axios[0]["purl"] == "pkg:npm/axios@0.21.1"
    repos = {p["value"] for p in axios[0]["properties"]}
    assert repos == {"team/web", "team/api"}


def test_runtimes_and_frameworks_are_components_too():
    doc = sbom.build_sbom(_inv(), _audit(), "2026-07-27")
    types = {(c["name"], c["type"]) for c in doc["components"]}
    assert ("php", "platform") in types
    assert ("laravel", "framework") in types
    assert ("laravel/framework", "library") in types       # the composer package, distinct


def test_cve_findings_become_vulnerabilities_linked_to_the_component():
    doc = sbom.build_sbom(_inv(), _audit(), "2026-07-27")
    vulns = doc["vulnerabilities"]
    assert len(vulns) == 1
    v = vulns[0]
    assert v["id"] == "CVE-2021-3749"
    assert v["ratings"][0]["severity"] == "high"
    assert v["source"]["name"] == "OSV"
    assert v["affects"] == [{"ref": "pkg:npm/axios@0.21.1"}]   # linked to the parts-list entry


def test_no_vulnerabilities_key_when_there_are_no_cves():
    doc = sbom.build_sbom(_inv(), {"findings": []}, "2026-07-27")
    assert "vulnerabilities" not in doc


def test_output_is_byte_identical_across_calls():
    import json
    a = json.dumps(sbom.build_sbom(_inv(), _audit(), "2026-07-27"), sort_keys=True)
    b = json.dumps(sbom.build_sbom(_inv(), _audit(), "2026-07-27"), sort_keys=True)
    assert a == b


def test_empty_fleet_is_a_valid_empty_sbom():
    doc = sbom.build_sbom({"repos": []}, {"findings": []}, "2026-07-27")
    assert doc["bomFormat"] == "CycloneDX" and doc["components"] == []

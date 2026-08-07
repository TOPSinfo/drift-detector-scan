"""SPDX 2.3 SBOM — a second standard format, sharing CycloneDX's component discovery.
Deterministic, no network."""
import json

from agent.lib import spdx


def _inv():
    return {"repos": [{"path": "team/web",
                       "sdks": [{"eco": "npm", "pkg": "axios", "resolved": "0.21.1"}],
                       "runtimes": {"php": {"range": "8.1"}}, "frameworks": {}}]}


def test_it_is_an_spdx_document():
    doc = spdx.build_spdx(_inv(), "2026-07-27")
    assert doc["spdxVersion"] == "SPDX-2.3"
    assert doc["SPDXID"] == "SPDXRef-DOCUMENT"
    assert doc["creationInfo"]["created"] == "2026-07-27T00:00:00Z"


def test_components_become_packages_with_a_purl_external_ref():
    doc = spdx.build_spdx(_inv(), "2026-07-27")
    axios = next(p for p in doc["packages"] if p["name"] == "axios")
    assert axios["versionInfo"] == "0.21.1"
    assert axios["externalRefs"][0]["referenceLocator"] == "pkg:npm/axios@0.21.1"
    # every package is DESCRIBES-related to the document
    assert any(r["relatedSpdxElement"] == axios["SPDXID"]
               and r["relationshipType"] == "DESCRIBES" for r in doc["relationships"])


def test_namespace_is_deterministic_from_content():
    a = spdx.build_spdx(_inv(), "2026-07-27")["documentNamespace"]
    b = spdx.build_spdx(_inv(), "2026-07-27")["documentNamespace"]
    assert a == b                                        # not random -> byte-identical output


def test_output_is_byte_identical():
    a = json.dumps(spdx.build_spdx(_inv(), "2026-07-27"), sort_keys=True)
    b = json.dumps(spdx.build_spdx(_inv(), "2026-07-27"), sort_keys=True)
    assert a == b

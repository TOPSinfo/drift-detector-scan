"""Emit an SPDX 2.3 SBOM from the inventory — the second standard SBOM format alongside
CycloneDX, for tooling/compliance that requires SPDX (e.g. some government + Linux-foundation
pipelines). Shares CycloneDX's component discovery so the two never disagree.

A VERIFIED projection of inventory.json — `verify` rebuilds it and fails on drift. Deterministic:
the document namespace is derived from the content (not random), created-time from `now`, and
every array is sorted -> byte-identical.
"""
from __future__ import annotations

import hashlib
import re

from agent.lib import sbom

SPDX_VERSION = "SPDX-2.3"


def _spdxid(ref: str) -> str:
    """A valid SPDXID (`SPDXRef-[A-Za-z0-9.-]+`) from a component bom-ref."""
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", str(ref)).strip("-") or "component"
    return f"SPDXRef-Package-{slug}"


def build_spdx(inventory: dict, now: str) -> dict:
    comps = sbom._finalize({**sbom._library_components(inventory),
                            **sbom._platform_components(inventory)})
    packages, relationships = [], []
    for c in comps:
        sid = _spdxid(c["bom-ref"])
        pkg = {"SPDXID": sid, "name": c["name"], "versionInfo": c.get("version") or "NOASSERTION",
               "downloadLocation": "NOASSERTION", "filesAnalyzed": False}
        if c.get("purl"):
            pkg["externalRefs"] = [{"referenceCategory": "PACKAGE-MANAGER",
                                    "referenceType": "purl", "referenceLocator": c["purl"]}]
        packages.append(pkg)
        relationships.append({"spdxElementId": "SPDXRef-DOCUMENT", "relatedSpdxElement": sid,
                              "relationshipType": "DESCRIBES"})
    packages.sort(key=lambda p: p["SPDXID"])
    relationships.sort(key=lambda r: r["relatedSpdxElement"])
    # a deterministic-but-unique document namespace: same components -> same namespace
    digest = hashlib.sha256("|".join(p["SPDXID"] for p in packages).encode()).hexdigest()[:16]
    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "drift-detector-sbom",
        "documentNamespace": f"https://topsinfosolutions.com/drift-detector/spdx/{digest}",
        "creationInfo": {"created": f"{now}T00:00:00Z",
                         "creators": ["Tool: Drift-Detector", "Organization: TOPS Infosolutions"]},
        "packages": packages,
        "relationships": relationships,
    }

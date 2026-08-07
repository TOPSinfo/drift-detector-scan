"""Emit a CycloneDX SBOM from the inventory — a VERIFIED PROJECTION, not a hand-built surface.

The scanner already inventories every third-party component (packages, runtimes, frameworks)
and audits them (OSV CVEs, endoflife EOL, vendor sunsets). A CycloneDX Software Bill of
Materials is a small, standard projection of that: the components as a parts list, plus the
CVE findings as `vulnerabilities` (SBOM + VEX). `drift-scan verify` re-derives the counts
from the inventory and audit and fails if the SBOM disagrees — the discipline whose absence
got the old, unverified CycloneDX exporter deleted.

Deterministic: no random serialNumber, the timestamp comes from the passed `now`, and every
array is sorted — same inputs -> byte-identical sbom.json.
"""
from __future__ import annotations

from agent.lib.purl import to_purl

SPEC_VERSION = "1.5"
_SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


def _add_repo(comp: dict, repo) -> None:
    if repo:
        comp.setdefault("_repos", set()).add(repo)


def _library_components(inventory: dict) -> dict:
    """One component per distinct (ecosystem, name, version) library across the whole fleet —
    a package used in two repos is ONE component, with both repos recorded."""
    by_ref: dict = {}
    for r in inventory.get("repos", []):
        repo = r.get("path")
        for s in r.get("sdks", []):
            eco, name = s.get("eco"), s.get("pkg")
            if not eco or not name:
                continue
            version = s.get("resolved") or s.get("ver")
            purl = to_purl(eco, name, version)
            ref = purl or f"lib:{eco}/{name}@{version or ''}"
            c = by_ref.setdefault(ref, {"type": "library", "name": name,
                                        "version": str(version or ""), "bom-ref": ref})
            if purl:
                c["purl"] = purl
            _add_repo(c, repo)
    return by_ref


def _platform_components(inventory: dict) -> dict:
    """Runtimes (php/node — DevOps' base image) and frameworks (laravel/django — app code)
    as components, so the SBOM covers the whole stack, not just libraries."""
    by_ref: dict = {}
    for r in inventory.get("repos", []):
        repo = r.get("path")
        for name, rt in (r.get("runtimes") or {}).items():
            ver = str((rt or {}).get("range") or "")
            c = by_ref.setdefault(f"runtime:{name}@{ver}",
                                  {"type": "platform", "name": name, "version": ver,
                                   "bom-ref": f"runtime:{name}@{ver}"})
            _add_repo(c, repo)
        for name, fw in (r.get("frameworks") or {}).items():
            ver = str((fw or {}).get("ver") or "")
            c = by_ref.setdefault(f"framework:{name}@{ver}",
                                  {"type": "framework", "name": name, "version": ver,
                                   "bom-ref": f"framework:{name}@{ver}"})
            _add_repo(c, repo)
    return by_ref


def _finalize(components_map: dict) -> list:
    """Deterministic component list: sorted by bom-ref, each carrying the repos it appears in
    as CycloneDX properties (traceability back to where the component is used)."""
    out = []
    for ref in sorted(components_map):
        c = dict(components_map[ref])
        repos = sorted(c.pop("_repos", set()))
        if repos:
            c["properties"] = [{"name": "drift:repo", "value": rp} for rp in repos]
        out.append(c)
    return out


def _vulnerabilities(audit: dict, components: list) -> list:
    """CVE findings -> CycloneDX vulnerabilities, linked to the component bom-ref they affect
    (SBOM + VEX). A finding whose component isn't in the parts list still appears — the vuln
    is real whether or not we resolved its exact component ref."""
    by_body: dict = {}                       # 'npm/axios' -> bom-ref
    for c in components:
        purl = c.get("purl", "")
        if purl.startswith("pkg:"):
            by_body.setdefault(purl[4:].split("@", 1)[0], c["bom-ref"])
    vulns: dict = {}
    for f in audit.get("findings", []):
        if f.get("kind") != "cve":
            continue
        cid = f.get("cve") or f.get("id")
        if not cid:
            continue
        bom_ref = by_body.get(f.get("ref"))
        key = (str(cid), str(bom_ref))
        if key in vulns:
            continue
        v = {"id": cid,
             "source": {"name": "OSV", "url": f.get("source_url") or "https://osv.dev"},
             "ratings": [{"severity": _SEV.get((f.get("severity") or "").upper(), "unknown")}]}
        if bom_ref:
            v["affects"] = [{"ref": bom_ref}]
        if f.get("recommendation"):
            v["recommendation"] = f["recommendation"]
        vulns[key] = v
    return [vulns[k] for k in sorted(vulns)]


def build_sbom(inventory: dict, audit: dict, now: str) -> dict:
    """A CycloneDX 1.5 SBOM (with vulnerabilities) as a pure function of the inventory + audit
    and the scan date. Deterministic: no serialNumber, timestamp from `now`, arrays sorted."""
    comps = _finalize({**_library_components(inventory), **_platform_components(inventory)})
    vulns = _vulnerabilities(audit, comps)
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "version": 1,
        "metadata": {
            "timestamp": f"{now}T00:00:00Z",
            "tools": [{"vendor": "TOPS Infosolutions", "name": "Drift Detector"}],
        },
        "components": comps,
    }
    if vulns:
        doc["vulnerabilities"] = vulns
    return doc

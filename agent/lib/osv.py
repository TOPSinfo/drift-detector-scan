"""OSV.dev client — look up known vulnerabilities for a package version.

https://api.osv.dev/v1/query : POST {package:{ecosystem,name}, version} -> {vulns:[...]}.
HTTP is injected (see http_util) so tests use canned responses.
"""
from __future__ import annotations

from agent.lib.http_util import default_http
from agent.lib.purl import osv_ecosystem
from agent.lib import cvss

OSV_QUERY_URL = "https://api.osv.dev/v1/query"


def _severity_label(vuln: dict) -> str:
    ds = vuln.get("database_specific") or {}
    sev = ds.get("severity")
    if sev:
        return str(sev).upper()                 # GHSA: LOW / MODERATE / HIGH / CRITICAL
    best = None                                  # else derive from any CVSS vector/score
    for s in vuln.get("severity") or []:
        score = s.get("score")
        val = None
        if isinstance(score, (int, float)):
            val = float(score)
        elif isinstance(score, str):
            val = cvss.base_score(score) if score.startswith("CVSS:") else _as_float(score)
        if val is not None and (best is None or val > best):
            best = val
    return cvss.label(best) if best is not None else "UNKNOWN"


def _as_float(s: str):
    try:
        return float(s)
    except ValueError:
        return None


def _cve(vuln: dict) -> str:
    for a in vuln.get("aliases") or []:
        if str(a).startswith("CVE-"):
            return a
    return vuln.get("id", "")


def _fixed_version(vuln: dict, ecosystem: str | None = None, name: str | None = None) -> str | None:
    # only the affected entry for the queried package/ecosystem — an advisory can list
    # ranges for several packages/ecosystems, whose 'fixed' would be a different package's.
    for aff in vuln.get("affected") or []:
        pkg = aff.get("package") or {}
        # skip only when the entry names a DIFFERENT package/ecosystem; missing = don't exclude
        if name and pkg.get("name") and pkg.get("name") != name:
            continue
        if ecosystem and pkg.get("ecosystem") and pkg.get("ecosystem") != ecosystem:
            continue
        for rng in aff.get("ranges") or []:
            for ev in rng.get("events") or []:
                if ev.get("fixed"):
                    return ev["fixed"]
    return None


def _source_url(vuln: dict) -> str:
    for r in vuln.get("references") or []:
        if r.get("url"):
            return r["url"]
    return f"https://osv.dev/vulnerability/{vuln.get('id', '')}"


def query_package(eco: str, name: str, version: str | None, *, http=default_http) -> list:
    """Return a list of normalized vuln dicts for one package version (empty if none/unsupported)."""
    osv_eco = osv_ecosystem(eco)
    if not osv_eco or not version:
        return []
    resp = http(OSV_QUERY_URL, method="POST",
                body={"package": {"ecosystem": osv_eco, "name": name}, "version": version})
    out = []
    for v in resp.get("vulns") or []:
        out.append({
            "id": v.get("id", ""),
            "cve": _cve(v),
            "severity": _severity_label(v),
            "summary": (v.get("summary") or (v.get("details") or "")[:160]).strip(),
            "fixed": _fixed_version(v, osv_eco, name),
            "url": _source_url(v),
        })
    return out


def query_all(packages, *, http=default_http) -> dict:
    """Dedupe (eco,name,version) across all repos and query each once. Returns {key: [vuln]}."""
    cache: dict = {}
    for eco, name, version in packages:
        key = (eco, name, version)
        if key not in cache:
            cache[key] = query_package(eco, name, version, http=http)
    return cache

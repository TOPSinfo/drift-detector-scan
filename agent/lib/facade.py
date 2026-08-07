"""Read-only query facade over the produced artifacts (inventory.json / audit.json) plus a
couple of LIVE checks. A pure, protocol-free read API over the scan artifacts — pure functions, unit-tested,
no protocol. The deterministic pipeline writes the data; this lets any assistant read it.
"""
from __future__ import annotations

import json
import os

from agent.lib import osv, eol
from agent.lib.http_util import default_http
from agent.lib.ranking import severity_rank, semver_key, is_version


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return None


def load_state(state_dir: str):
    return (_read_json(os.path.join(state_dir, "inventory.json")) or {},
            _read_json(os.path.join(state_dir, "audit.json")) or {})


def list_repos(inventory: dict) -> list:
    out = []
    for r in inventory.get("repos", []):
        out.append({
            "repo": r.get("path"),
            "apis": sorted({e.get("vendor") for e in r.get("endpoints", []) if e.get("vendor")}),
            "runtimes": {k: (v or {}).get("range") for k, v in (r.get("runtimes") or {}).items()},
            "packages": len(r.get("sdks", [])),
        })
    return out


def query_integrations(inventory: dict, vendor: str | None = None, repo: str | None = None) -> list:
    out = []
    for r in inventory.get("repos", []):
        if repo and r.get("path") != repo:
            continue
        for e in r.get("endpoints", []):
            if vendor and e.get("vendor") != vendor:
                continue
            out.append({"repo": r.get("path"), "vendor": e.get("vendor"),
                        "version": e.get("version"), "files": e.get("files", [])})
    return out


def get_findings(audit: dict, repo: str | None = None, status: str | None = None) -> list:
    want = status.upper() if status else None
    keys = ("repo", "kind", "ref", "version", "status", "detail", "recommendation", "source_url", "files")
    out = []
    for f in audit.get("findings", []):
        if f.get("suppressed"):
            continue
        if repo and f.get("repo") != repo:
            continue
        if want and f.get("status") != want:
            continue
        out.append({k: f.get(k) for k in keys if f.get(k) is not None})
    return out


def check_dependency(ecosystem: str, name: str, version: str, *, http=None) -> dict:
    """LIVE OSV lookup for a specific package version — generation-time prevention."""
    base = {"ecosystem": ecosystem, "package": name, "version": version}
    try:
        vulns = osv.query_package(ecosystem, name, version, http=http or default_http)
    except Exception as exc:
        return {**base, "checked": False, "error": f"OSV unavailable: {exc}"}
    worst = max((v.get("severity", "") for v in vulns), key=severity_rank, default=None)
    fixes = sorted({v["fixed"] for v in vulns if v.get("fixed") and is_version(v["fixed"])},
                   key=semver_key)   # numeric, not string sort
    return {
        **base, "checked": True,
        "vulnerable": bool(vulns), "count": len(vulns), "worst_severity": worst,
        "cves": [v["cve"] for v in vulns[:10] if v.get("cve")],
        "recommendation": (f"{len(vulns)} known advisories; upgrade to ≥ {fixes[-1]}" if fixes
                           else (f"{len(vulns)} known advisories" if vulns else "no known advisories")),
    }


def check_runtime(product: str, version: str, now: str, *, http=None) -> dict:
    """LIVE endoflife.date lookup for a runtime/framework version."""
    try:
        res = eol.check(product, version, now, http=http or default_http)
    except Exception as exc:
        return {"product": product, "version": version, "checked": False, "error": f"endoflife.date unavailable: {exc}"}
    if not res:
        return {"product": product, "version": version, "checked": True, "tracked": False}
    return {"product": product, "version": version, "checked": True, "tracked": True,
            "status": res["status"], "eol_date": res.get("eol_date"), "recommended": res.get("recommended")}

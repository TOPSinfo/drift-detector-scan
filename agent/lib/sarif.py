"""Emit a SARIF 2.1.0 report of the findings — the standard static-analysis result format
that GitHub code scanning and IDEs render inline. Its edge here: the findings carry real
`file:line` call sites (a retired vendor API at src/…:72), so SARIF places them AS annotations
on the exact lines, not just a list.

A VERIFIED projection of the audit findings — `verify` rebuilds it and fails on drift.
Deterministic: results + rules sorted, no timestamps in the payload.
"""
from __future__ import annotations

SARIF_VERSION = "2.1.0"
_LEVEL = {"DEPRECATED": "error", "REVIEW": "warning"}
_RULES = {
    "cve": ("drift-cve", "Known vulnerability (OSV)"),
    "sunset": ("drift-vendor-sunset", "Retired or retiring vendor API"),
    "eol": ("drift-eol", "End-of-life runtime or framework"),
}
_INFO_URI = "https://github.com/TOPSinfo/drift-detector-scan"


def _loc_str(fl) -> str:
    """A call-site entry is EITHER a dict {loc: 'path:line'} or a bare 'path:line' string —
    both shapes exist in findings (see md_render._first_loc). Normalize to the string."""
    return (fl.get("loc", "") if isinstance(fl, dict) else str(fl)) or ""


def _location(repo: str, loc: str) -> dict:
    """A SARIF physicalLocation from a 'path/to/file:line' call site."""
    uri, sep, line = str(loc).rpartition(":")
    if not (sep and line.isdigit()):
        uri, line = str(loc), None
    phys = {"artifactLocation": {"uri": f"{repo}/{uri}" if repo else uri}}
    if line is not None:
        phys["region"] = {"startLine": int(line)}
    return {"physicalLocation": phys}


def _first_loc(f: dict) -> str:
    files = f.get("files") or []
    return _loc_str(files[0]) if files else ""


def build_sarif(audit: dict) -> dict:
    findings = sorted(audit.get("findings", []),
                      key=lambda f: (f.get("repo", ""), f.get("kind", ""), f.get("ref", ""),
                                     str(f.get("id") or f.get("date") or ""), _first_loc(f)))
    rules_used: dict = {}
    results = []
    for f in findings:
        rid, rname = _RULES.get(f.get("kind"), ("drift-finding", "Drift finding"))
        rules_used[rid] = rname
        text = f.get("detail") or f"{f.get('ref')} {f.get('status')}"
        rec = f.get("recommendation")
        r = {"ruleId": rid, "level": _LEVEL.get(f.get("status"), "note"),
             "message": {"text": text + (f" — {rec}" if rec else "")}}
        locs = [_location(f.get("repo"), _loc_str(fl))
                for fl in (f.get("files") or []) if _loc_str(fl)]
        if locs:
            r["locations"] = locs
        if f.get("source_url"):
            r["properties"] = {"source": f["source_url"]}
        results.append(r)
    rules = [{"id": rid, "name": rname, "shortDescription": {"text": rname}}
             for rid, rname in sorted(rules_used.items())]
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {"driver": {"name": "Drift Detector", "informationUri": _INFO_URI,
                                "rules": rules}},
            "results": results,
        }],
    }

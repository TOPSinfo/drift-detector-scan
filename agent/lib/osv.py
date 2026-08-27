"""OSV.dev client — look up known vulnerabilities for a package version.

https://api.osv.dev/v1/query : POST {package:{ecosystem,name}, version} -> {vulns:[...]}.
HTTP is injected (see http_util) so tests use canned responses.
"""
from __future__ import annotations

from agent.lib.http_util import default_http
from agent.lib.purl import osv_ecosystem
from agent.lib import cvss

OSV_QUERY_URL = "https://api.osv.dev/v1/query"
OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"

# Queries per querybatch request. OSV documents NO maximum, so this is not an API limit and must
# not be described as one — it is a bound WE choose. It exists because OSV paginates once a whole
# queryset exceeds 3,000 vulnerabilities; smaller chunks keep most responses to a single page,
# which keeps the request count predictable. Pagination is still followed when it happens.
BATCH_CHUNK = 200


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


def _normalise(vuln: dict, osv_eco: str | None = None, name: str | None = None) -> dict:
    """One raw OSV record -> the six keys the audit consumes.

    The ONLY place this shape is built. `query_package` and the batch path both go through here,
    so the two lookup routes cannot drift apart in what they claim about a vulnerability — a
    divergence would show up as findings that differ by which code path fetched them, which is
    the hardest kind of bug to see in a report.
    """
    return {
        "id": vuln.get("id", ""),
        "cve": _cve(vuln),
        "severity": _severity_label(vuln),
        "summary": (vuln.get("summary") or (vuln.get("details") or "")[:160]).strip(),
        "fixed": _fixed_version(vuln, osv_eco, name),
        "url": _source_url(vuln),
    }


def query_package(eco: str, name: str, version: str | None, *, http=default_http) -> list:
    """Return a list of normalized vuln dicts for one package version (empty if none/unsupported).

    Kept alongside the batch path rather than replaced by it: it is the equivalence ORACLE the
    batch path is tested against, and the right route for a caller holding a single key.
    """
    osv_eco = osv_ecosystem(eco)
    if not osv_eco or not version:
        return []
    resp = http(OSV_QUERY_URL, method="POST",
                body={"package": {"ecosystem": osv_eco, "name": name}, "version": version})
    return [_normalise(v, osv_eco, name) for v in resp.get("vulns") or []]


def query_all(packages, *, http=default_http) -> dict:
    """Dedupe (eco,name,version) across all repos and query each once. Returns {key: [vuln]}."""
    cache: dict = {}
    for eco, name, version in packages:
        key = (eco, name, version)
        if key not in cache:
            cache[key] = query_package(eco, name, version, http=http)
    return cache


def _batch_ids(keys, *, http=default_http, chunk: int = BATCH_CHUNK) -> dict:
    """{(eco, name, version): [vuln id, ...]} for every key, in OSV's order, all pages followed.

    `querybatch` answers POSITIONALLY: `results[i]` belongs to `queries[i]`, and nothing in the
    response identifies the package. Index is therefore the only correct join, and a short
    `results` array is unrecoverable rather than merely odd — hence the ValueError. Guessing which
    key lost its result would attribute one package's vulnerabilities to another.
    """
    out = {tuple(k): [] for k in keys}
    # The same filter query_package applies, applied BEFORE the request so an unsupported
    # ecosystem or a version-less package never occupies a slot in the batch.
    askable = [(tuple(k), osv_ecosystem(k[0])) for k in keys]
    askable = [(k, eco) for k, eco in askable if eco and k[2]]
    for i in range(0, len(askable), chunk):
        window = askable[i:i + chunk]
        pending = [{"package": {"ecosystem": eco, "name": k[1]}, "version": k[2]}
                   for k, eco in window]
        owners = [k for k, _eco in window]
        while pending:
            resp = http(OSV_QUERYBATCH_URL, method="POST", body={"queries": pending})
            results = resp.get("results") or []
            if len(results) != len(pending):
                raise ValueError(
                    f"OSV querybatch returned {len(results)} results for {len(pending)} queries — "
                    f"the index join is undefined, so no vulnerability can be attributed safely")
            # page_token is per-QUERY: only the queries that reported more pages are resent,
            # otherwise the finished ones would return their ids a second time.
            nxt_q, nxt_owners = [], []
            for q, owner, res in zip(pending, owners, results, strict=True):
                out[owner].extend(v.get("id", "") for v in res.get("vulns") or [])
                token = res.get("next_page_token")
                if token:
                    nxt_q.append({**q, "page_token": token})
                    nxt_owners.append(owner)
            pending, owners = nxt_q, nxt_owners
    return out

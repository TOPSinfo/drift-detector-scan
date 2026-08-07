"""The PROBABILISTIC overlay: compare an AI cross-check (ai_results) against the certified
endpoints (drift.json["endpoints"]) into a three-way diff. Pure + deterministic — the AI's
non-determinism is upstream, captured in ai_results.json. This module invents nothing and
certifies nothing; its output is explicitly UNVERIFIED and rendered as a separate artifact."""
from __future__ import annotations

import re

_FIRST = re.compile(r"[ (/]")


def norm(vendor: str) -> str:
    """A vendor's coverage key: first token, lowercased. 'Amazon SP-API' -> 'amazon'. This is
    coarse ON PURPOSE — the AI names vendors in prose, the tool in records; matching the head
    token compares COVERAGE (did each see this vendor at all), not exact endpoint strings."""
    return _FIRST.split(str(vendor or "").strip())[0].strip().lower()


def compare(ai_results: dict, certified_endpoints: list, scanned_repos=None) -> dict:
    # certified vendors per repo (classified only)
    tool_by_repo: dict = {}
    for e in certified_endpoints:
        if not e.get("classified"):
            continue
        v = norm(e.get("vendor"))
        if v and v != "unknown":
            tool_by_repo.setdefault(e.get("repo"), set()).add(v)

    ai_by_repo = {r.get("repo"): r for r in ai_results.get("repos", [])}
    # scanned_repos is the AUTHORITATIVE roster (every repo the deterministic scan touched,
    # including ones with zero classified endpoints — a blind-spot BY DEFINITION). Without it,
    # a repo blind to both tool and AI would vanish from every surface below ("cannot see" must
    # never render as "clean"). When omitted, this degrades to today's (tool ∪ ai) universe.
    scanned = set(scanned_repos or []) | set(tool_by_repo) | set(ai_by_repo)
    agree = aionly = toolonly = 0
    by_repo = []
    for repo in sorted(scanned):
        tool_v = tool_by_repo.get(repo, set())
        ai_r = ai_by_repo.get(repo)
        ai_ints = (ai_r or {}).get("integrations", [])
        ai_v = {norm(i.get("vendor")) for i in ai_ints if norm(i.get("vendor"))}
        a = sorted(tool_v & ai_v)
        t = sorted(tool_v - ai_v)
        # aiOnly LEADS keep their full record (the actionable part); dedupe+sort by vendor
        leads_seen, leads = set(), []
        for i in sorted(ai_ints, key=lambda x: (norm(x.get("vendor")), str(x.get("file")))):
            nv = norm(i.get("vendor"))
            if nv and nv not in tool_v and nv not in leads_seen:
                leads_seen.add(nv)
                leads.append({"vendor": i.get("vendor"), "endpoint": i.get("endpoint", ""),
                              "file": i.get("file", ""), "line": str(i.get("line", "")),
                              "retired": i.get("retired", "unknown"), "note": i.get("note", "")})
        agree += len(a); toolonly += len(t); aionly += len(leads)
        by_repo.append({"repo": repo, "agree": a, "toolOnly": t, "aiOnly": leads})

    not_checked = sorted(scanned - set(ai_by_repo))
    return {"tallies": {"agree": agree, "aiOnly": aionly, "toolOnly": toolonly,
                        "reposReadByAI": len(ai_by_repo), "reposScanned": len(scanned)},
            "notCrossChecked": not_checked,
            "byRepo": by_repo}

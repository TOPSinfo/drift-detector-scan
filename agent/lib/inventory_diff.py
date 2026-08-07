"""Diff two superset inventory docs into a structured change set (what usage changed since last scan)."""
from __future__ import annotations


def _endpoints(repo) -> set:
    return {(e.get("techKey", ""), e.get("domain", ""), e.get("version"))
            for e in repo.get("endpoints", [])}


def _sdks(repo) -> dict:
    return {(s.get("eco", ""), s.get("pkg", "")): s.get("ver", "") for s in repo.get("sdks", [])}


def _runtimes(repo) -> dict:
    return {name: (rt or {}).get("range", "") for name, rt in (repo.get("runtimes") or {}).items()}


def _fmt_eps(tuples) -> list:
    return [{"techKey": tk, "domain": d, "version": v}
            for tk, d, v in sorted(tuples, key=lambda x: (x[0], x[1], str(x[2])))]


def _diff_repo(path, pr, cr) -> dict:
    pe, ce = _endpoints(pr), _endpoints(cr)
    ps, cs = _sdks(pr), _sdks(cr)
    prt, crt = _runtimes(pr), _runtimes(cr)
    return {
        "repo": path,
        "endpointsAdded": _fmt_eps(ce - pe),
        "endpointsRemoved": _fmt_eps(pe - ce),
        "sdksAdded": [{"eco": e, "pkg": p, "ver": cs[(e, p)]} for e, p in sorted(set(cs) - set(ps))],
        "sdksRemoved": [{"eco": e, "pkg": p, "ver": ps[(e, p)]} for e, p in sorted(set(ps) - set(cs))],
        "sdkVersionChanges": [{"eco": e, "pkg": p, "from": ps[(e, p)], "to": cs[(e, p)]}
                              for e, p in sorted(set(ps) & set(cs)) if ps[(e, p)] != cs[(e, p)]],
        "runtimeChanges": [{"product": n, "from": prt[n], "to": crt[n]}
                           for n in sorted(set(prt) & set(crt)) if prt[n] != crt[n]],
    }


def diff_inventories(prev: dict, curr: dict) -> dict:
    p = {r["path"]: r for r in prev.get("repos", [])}
    c = {r["path"]: r for r in curr.get("repos", [])}
    changes = []
    for path in sorted(set(p) & set(c)):
        ch = _diff_repo(path, p[path], c[path])
        if any(ch[k] for k in ch if k != "repo"):
            changes.append(ch)
    return {"reposAdded": sorted(set(c) - set(p)),
            "reposRemoved": sorted(set(p) - set(c)),
            "changes": changes}

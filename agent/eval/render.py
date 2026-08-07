"""Render a scorecard dict into a terminal table. Pure (string in, string out).
Noise is printed right next to recall so recall can't be read in isolation."""
from __future__ import annotations


def _pct(x):
    return "—" if x is None else f"{round(x * 100)}%"


def render_scorecard(sc: dict) -> str:
    s = sc["summary"]
    rc = s["recall"]
    gate = "PASS" if sc["gate"]["passed"] else "FAIL"
    lines = [f"drift-eval · {sc['category']} · {sc.get('now', '')}".rstrip(), ""]
    lines.append(f"RECALL   {rc['passed']}/{rc['total']} detect vendor   [{gate}]")
    lines.append(f"         endpoint {rc['endpoint']} · sdk-only {rc['sdk_only']} · "
                 f"known-miss {rc['known_miss']} · holdout {rc['holdout']}")
    lines.append(f"noise    median {s['noise']['median']} · max {s['noise']['max']} unknown hosts/repo  (info)")
    lines.append(f"version  {_pct(s['version_rate'])} of {s.get('versionable', 0)} URL-versionable "
                 f"endpoints extracted · {s.get('no_url_version', 0)} have no URL version  (info)")
    lines.append(f"sunset   {s['sunset_match']['hit']}/{s['sunset_match']['expected']} expected fired  (info)")
    lines.append(f"errored  {s['errored']}")
    lines += ["", "repo                                   detect  via       noise  ver   sunset"]
    for r in sc["repos"]:
        det = "✓" if r["detected"] else ("known" if r["miss_mode"] not in (None, "unattributed") else "✗")
        sun = "—" if not r["sunset_expected"] else ("✓" if r["sunset_hit"] else "✗")
        lines.append(f"{r['repo'][:36]:36}  {det:6}  {str(r['via'] or '-'):8}  "
                     f"{r['noise']:>4}   {_pct(r['version_rate']):>4}  {sun}")
    if not sc["gate"]["passed"]:
        lines += ["", f"GATE FAILED — undetected (non-known-gap): {', '.join(sc['gate']['failures'])}"]
    return "\n".join(lines) + "\n"

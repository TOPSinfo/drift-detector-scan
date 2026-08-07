"""The pre-scan scope gate — assemble a reviewable map of what a run WILL and WON'T read,
and refuse (non-zero) when a blind spot hasn't been acknowledged.

This is the setup ritual: edit the fleet, run `probe`, read the map, then `run`. It says up
front what the coverage sections say only after a scan — which sources resolve, how deep the
walk goes, and (the piece nothing else computes) which private deps a repo pulls in that are
NOT themselves scanned. "Cannot see" is declared before the scan, not discovered after it.

Pure and deterministic: gathered facts in, rendered text + exit code out. The CLI does the
I/O (resolve, clone, census); this decides and renders. Same facts → byte-identical report.
"""
from __future__ import annotations

from urllib.parse import urlparse

from agent.lib.manifest_scan import _SKIP_DIRS

# Blind spots that trip the gate unless acknowledged. A structural skip (vendor/) is NOT a
# hole — it's how the tool works; only holes a real integration could hide behind count.
GATE_TRIPPED = 3      # open (unacknowledged) scope hole(s) — fits the 0/2/3/4 exit contract
NOTHING = 4           # nothing resolves — can't even scope
CLEAN = 0


def _last_seg(url: str) -> str:
    p = urlparse(url).path if "://" in (url or "") else (url or "")
    seg = p.rstrip("/").rsplit("/", 1)[-1]
    return seg[:-4] if seg.endswith(".git") else seg


def _holes(facts: dict) -> list:
    """Every blind spot, each with a stable `gap` id a human can paste into drift.yml to
    acknowledge it. kind ∈ {repo, dep, lang}."""
    out = []
    for e in facts.get("errors", []):
        seg = _last_seg(e.get("root", "")) or "?"
        out.append({"kind": "repo", "gap": f"repo:{seg}",
                    "label": f"{seg} — unreachable ({e.get('reason', 'did not resolve')})"})
    for row in facts.get("edges", []):
        for m in row.get("missing", []):
            gid = m["id"] or m["url"]
            out.append({"kind": "dep", "gap": f"dep:{gid}",
                        "label": f"{gid} — referenced by {row['repo']}, not in fleet"})
    for lang in sorted(facts.get("unmodeledLangs", {})):
        repos = facts["unmodeledLangs"][lang]
        out.append({"kind": "lang", "gap": f"lang:{lang}",
                    "label": f"{lang} — no egress rules ({len(repos)} repo(s): "
                             f"{', '.join(sorted(repos)[:4])})"})
    return out


def _markdown(facts: dict, holes: list, code: int) -> str:
    """A GitHub-flavored markdown view of the scope map — for `$GITHUB_STEP_SUMMARY`, so the
    targeted-vs-covered scope shows on the CI run's Summary page instead of buried in a log."""
    projects = facts.get("projects", [])
    verdicts = [r.get("verdict") for r in facts.get("repos", [])]
    known = sum(1 for v in verdicts if v == "KNOWN")
    unknown = sum(1 for v in verdicts if v == "UNKNOWN")
    open_n = sum(1 for h in holes if not h["accepted"])
    blind = sum(1 for h in holes if h["kind"] == "dep" and not h["accepted"])
    status = ("✓ scope clean" if code == CLEAN else
              "✗ nothing resolved" if code == NOTHING else f"✗ {open_n} open scope hole(s)")

    L = [f"## Drift probe · {facts.get('host') or 'local'}", ""]
    L.append(f"**{len(projects)} repo(s) in scope** · {known} KNOWN · {unknown} UNKNOWN · "
             f"**{blind} blind dep(s)** · verdict: {status}")
    L.append("")
    edges = facts.get("edges", [])
    if edges:
        L += ["### Dependency scope", "",
              "| Repo | Covered (in fleet) | Blind (not in fleet) |", "|---|---|---|"]
        for row in edges:
            cov = ", ".join(e["id"].rsplit("/", 1)[-1] for e in row.get("present", [])) or "—"
            bl = ", ".join((e["id"] or e["url"]).rsplit("/", 1)[-1]
                           for e in row.get("missing", [])) or "—"
            L.append(f"| {row['repo']} | {cov} | {bl} |")
        L.append("")
    errs = facts.get("errors", [])
    if errs:
        L += ["### Unreachable sources", ""]
        L += [f"- {_last_seg(e.get('root', '')) or '?'} — {e.get('reason', '')}" for e in errs]
        L.append("")
    if holes:
        L += ["### Won't read (blind spots)", ""]
        for h in holes:
            tag = f"acknowledged — {h['reason']}" if h["accepted"] else "**OPEN**"
            L.append(f"- `{h['gap']}` — {h['label']} [{tag}]")
        L.append("")
    return "\n".join(L)


def assess(facts: dict) -> dict:
    """{text, markdown, exit_code, holes}. `facts` carries the gathered scope (see _cmd_probe)."""
    accepted = {a["gap"]: a.get("reason", "") for a in facts.get("accept", [])}
    holes = _holes(facts)
    for h in holes:
        h["accepted"] = h["gap"] in accepted
        h["reason"] = accepted.get(h["gap"], "")
    open_holes = [h for h in holes if not h["accepted"]]

    projects = facts.get("projects", [])
    if not projects:
        code = NOTHING
    elif open_holes:
        code = GATE_TRIPPED
    else:
        code = CLEAN

    L = [f"drift probe · {facts.get('host') or 'local'}"]

    # ── SCOPE ──
    errs = facts.get("errors", [])
    L.append("SCOPE")
    L.append(f"  {len(projects) + len(errs)} source(s) → {len(projects)} resolve"
             + (f" · {len(errs)} unreachable" if errs else ""))
    verdicts = [r.get("verdict") for r in facts.get("repos", [])]
    known = sum(1 for v in verdicts if v == "KNOWN")
    unknown = sum(1 for v in verdicts if v == "UNKNOWN")
    unscanned = sum(1 for v in verdicts if v not in ("KNOWN", "UNKNOWN"))
    L.append(f"  predicted: {known} KNOWN · {unknown} UNKNOWN · {unscanned} not-yet-scanned")
    langsig = facts.get("languageSignal") or {}
    if langsig:
        bits = [f"{lang} {'✓modeled' if ok else '✗no-egress-rules'}"
                for lang, ok in sorted(langsig.items())]
        L.append(f"  languages: {' · '.join(bits)}")

    # ── DEPTH ──
    L.append("DEPTH")
    L.append(f"  reads repo source · skips {'/, '.join(sorted(_SKIP_DIRS))}/")
    L.append("  parses manifests (deps + locked versions) · does NOT descend into dependency "
             "source (see EDGES)")

    # ── EDGES ──
    edges = facts.get("edges", [])
    L.append("EDGES  (private deps referenced across the fleet)")
    if not edges:
        L.append("  none — no repo declares a private VCS dependency")
    for row in edges:
        present = [e["id"] for e in row.get("present", [])]
        missing = [e["id"] or e["url"] for e in row.get("missing", [])]
        L.append(f"  {row['repo']} → {len(present) + len(missing)} private dep(s):")
        if present:
            L.append(f"     ✓ in fleet: {', '.join(present)}")
        if missing:
            L.append(f"     ✗ MISSING : {', '.join(missing)}")

    # ── WON'T READ ──
    L.append("WON'T READ  (blind spots declared up front)")
    L.append(f"  • all {'/, '.join(sorted(_SKIP_DIRS))}/ — dependency internals, by design")
    for h in holes:
        tag = f"ACCEPTED: {h['reason']}" if h["accepted"] else "OPEN — acknowledge or fix"
        L.append(f"  • {h['label']}  [{tag}]  ({h['gap']})")

    # ── CREDS ──
    creds = facts.get("creds")
    if creds is not None:
        L.append("CREDS")
        L.append(f"  {'✓' if creds.get('ok') else '✗'} {creds.get('detail', '')}")

    # ── VERDICT ──
    if code == CLEAN:
        L.append("VERDICT  ✓ scope clean — every blind spot is structural or acknowledged")
    elif code == NOTHING:
        L.append("VERDICT  ✗ nothing resolved — fix the sources above before running (exit 4)")
    else:
        L.append(f"VERDICT  ✗ {len(open_holes)} open scope hole(s) — fix, or acknowledge in "
                 f"drift.yml `probe.accept` with a reason (exit 3)")

    return {"text": "\n".join(L), "markdown": _markdown(facts, holes, code),
            "exit_code": code, "holes": holes}

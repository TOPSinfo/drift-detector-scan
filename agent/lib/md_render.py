"""Render the report payload as Markdown — the primary, agent-readable view.

WHY MARKDOWN IS THE PRIMARY VIEW. An LLM cannot see rendered HTML/CSS; it verifies the
dashboard only by proxy, which is how two bugs shipped (a tile reading "Sunsets 1" over
twelve findings; twelve table rows rendering the identical label). Markdown SOURCE is text
an agent reads directly, so "what the agent checks" and "what a person sees" become nearly
the same artifact — and the remaining gap (Markdown's own grammar) is policeable by a
stdlib parser, which HTML's gap never was.

That gap is real: an unescaped `|` in a table cell silently truncates the row on GitHub
(extra cells dropped). So EVERY cell goes through `_esc`, the single choke point, and
`agent/lib/verify.py::check_md_matches_payload` re-parses this output and diffs it against
the payload. This is a VERIFIED PROJECTION of drift.json, never a parallel hand-built
truth — the discipline whose absence got the old Markdown/SARIF renderers deleted in v0.5.

Deterministic: pure function of the payload, `json.dumps`-stable upstream.
"""
from __future__ import annotations

from datetime import date as _date

from agent.lib import owners

SCHEMA_VERSION = "drift/v1"


def _esc(s) -> str:
    """Escape a value for a GFM table cell. Pipes break columns; newlines break the row.
    This is the ONLY place cells are escaped — a second escaper is a second bug."""
    return (str(s if s is not None else "")
            .replace("\\", "\\\\").replace("|", "\\|")
            .replace("\r", "").replace("\n", " ").strip())


def _table(headers: list, rows: list) -> list:
    """A GFM pipe table as a list of lines. Every cell escaped; a row with the wrong
    column count is a bug the parity check will catch."""
    out = ["| " + " | ".join(_esc(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_esc(c) for c in row) + " |")
    return out


def _repo(a: dict) -> str:
    """Display name for a repo: the clean project path (repoLabel, e.g. example-org/amazonspapi)
    the projection stamps, else the raw repo path."""
    return a.get("repoLabel") or a.get("repo") or ""


def _action_label(a: dict) -> str:
    """'eBay GetCategoryFeatures' for a sunset, 'composer/aws/aws-sdk-php' for a CVE."""
    ref = a.get("ref") or ""
    unit = a.get("unit")
    return f"{ref} {unit}" if unit else ref


def _first_loc(a: dict) -> str:
    files = a.get("files") or []
    if not files:
        return ""
    f0 = files[0]
    return f0.get("loc", "") if isinstance(f0, dict) else str(f0)


def _overdue(a: dict, now: str) -> bool:
    d = a.get("date")
    return bool(d and str(d) <= now)


def _gantt_txt(s) -> str:
    """Strip chars that break a gantt/quadrant label (':' is gantt's name/spec separator; the
    rest break mermaid generally). '/' '.' '-' are kept so API paths stay readable."""
    s = str(s if s is not None else "")
    for ch in ':#"<>[]{}\\|':
        s = s.replace(ch, " ")
    return " ".join(s.split()) or "?"


def _gantt(sunsets: list, now: str) -> list:
    """A retirement timeline: each dated surface a milestone, sectioned by vendor, crit = past."""
    dated = [a for a in sunsets if a.get("date")]
    if not dated:
        return []
    by_vendor: dict = {}
    for a in dated:
        by_vendor.setdefault(a.get("ref") or "?", []).append(a)
    L = ["```mermaid", "gantt", "  title Retirement timeline",
         "  dateFormat YYYY-MM-DD", "  axisFormat %b %Y"]
    for vendor in sorted(by_vendor):
        L.append(f"  section {_gantt_txt(vendor)}")
        for a in sorted(by_vendor[vendor], key=lambda x: str(x["date"])):
            tag = "crit" if _overdue(a, now) else "active"
            L.append(f"    {_gantt_txt(a.get('unit') or a.get('ref'))} :{tag}, milestone, {a['date']}, 0d")
    L.append("```")
    return L

def _diagrams(actions: list, now: str) -> list:
    """A retirement timeline of the sunset surfaces, AFTER the report so it never pushes the
    tables down. gantt milestones by vendor: crit (red) = already removed, active = ahead."""
    block = _gantt([a for a in actions if a.get("kind") == "sunset"], now)
    if not block:
        return []
    return ["## Retirement timeline", "",
            "_When each retiring API surface this code calls goes away — "
            "red = already removed, blue = still ahead._", "", *block, ""]


def render_markdown(payload: dict, now: str) -> str:
    """The report as Markdown. `now` dates the header and splits past-due from upcoming."""
    counts = payload.get("counts", {})
    actions = payload.get("actions", [])
    L: list = []

    # --- front matter: the projection self-identifies its source + contract version,
    # taken FROM the payload so the two cannot disagree ---
    L += ["---",
          f"schemaVersion: {_esc(payload.get('schemaVersion', SCHEMA_VERSION))}",
          "generatedFrom: drift.json",
          f"generated: {_esc(payload.get('generated', now))}",
          "---", ""]

    # --- headline ---
    scanned = counts.get("reposScanned", 0)
    affected = counts.get("reposAffected", 0)
    fixes = counts.get("fixes", 0)
    sunsets = [a for a in actions if a.get("kind") == "sunset"]
    past = [a for a in sunsets if a.get("date") and str(a["date"]) <= now]
    L.append("# Drift report")
    L.append("")
    if past:
        L.append(f"**{len(past)} of {len(sunsets)} retiring API surface(s) are already past "
                 f"their removal date** — calls into APIs the vendor has switched off. "
                 f"{fixes} fix(es) needed across {affected} of {scanned} repo(s).")
    elif fixes:
        L.append(f"**{fixes} fix(es) needed across {affected} of {scanned} repo(s).**")
    else:
        L.append(f"**No action-required findings across {scanned} repo(s) scanned.**")
    L.append("")

    # --- most-urgent callout: name the single most pressing surface so the reader has one
    # thing to do first. Most-overdue retired sunset wins; else the soonest deadline. Prose
    # (not parity-checked) — a pointer INTO the tables below, never a substitute for them.
    dated = [a for a in sunsets if a.get("date")]
    overdue = sorted((a for a in dated if str(a["date"]) <= now), key=lambda a: str(a["date"]))
    upcoming = sorted((a for a in dated if str(a["date"]) > now), key=lambda a: str(a["date"]))
    pick = overdue[0] if overdue else (upcoming[0] if upcoming else None)
    if pick:
        verb = "already retired" if str(pick["date"]) <= now else "retires"
        L.append(f"**Most urgent:** {_esc(_action_label(pick))} in "
                 f"`{_esc(_repo(pick))}` — {verb} {_esc(pick['date'])}.")
        L.append("")

    # --- couldn't-scan: sources requested but unreadable. Sits HIGH, before findings,
    # because "cannot see" is not "clean" — a report must never look green over a repo it
    # silently failed to open (a 404/no-access URL, a typo, a folder with no code). Rendered
    # as a table so verify re-parses it and confirms every requested root is actually named.
    unscannable = payload.get("rootsUnscannable", [])
    if unscannable:
        L.append(f"## ⚠ Couldn't scan ({len(unscannable)})")
        L.append("")
        L.append("_Sources you asked for that could **not** be read — this is not a clean "
                 "result for them. Check the path exists and the token has access._")
        L.append("")
        L += _table(["Source", "Why"],
                    [[u.get("root", ""), u.get("reason", "")] for u in unscannable])
        L.append("")

    # --- summary (the tiles, as a table) ---
    L.append("## Summary")
    L.append("")
    summary_rows = [
        ["Fixes needed (action-required)", counts.get("fixes", 0)],
        ["Vendor API sunsets", counts.get("sunsets", 0)],
        ["— of which already retired (past-due)", counts.get("pastDue", 0)],
        ["Runtime/framework EOL", counts.get("eol", 0)],
        ["Critical CVEs", counts.get("critical", 0)],
        ["Unaudited vendors", counts.get("unaudited", 0)],
        ["Repos affected / scanned", f"{affected} / {scanned}"],
    ]
    if unscannable:                       # only show the row when there's something to admit
        summary_rows.append(["Sources unscannable (not read)", counts.get("unscannable", 0)])
    L += _table(["Metric", "Count"], summary_rows)
    L.append("")

    # --- findings, split into the two delivery queues (DevOps vs Developer) ---
    # Repo is the FIRST column of every table: the same finding (a vendored SDK, a shared
    # runtime) can appear in several repos with an identical repo-relative call-site, so
    # without the repo those rows render byte-identical — a reader cannot tell which repo is
    # exposed, and the md-row-identity check (correctly) rejects the report. The repo is the
    # disambiguator AND the thing a reader most needs: which of my repos does this hit.
    def _render_group(group, cols, is_sunset):
        rows = []
        for a in group:
            when = a.get("date") or a.get("fix_version") or "—"
            # call-sites the reader can act on (the located files), not finding_count —
            # which for a family-scoped sunset is ~always 1 and tells the reader nothing
            sites = len(a.get("files") or []) or a.get("finding_count", 0)
            rows.append([_repo(a), _action_label(a), a.get("status", ""),
                         when, sites, _first_loc(a)])
        L.extend(_table(cols, rows))
        L.append("")
        # (the visual charts live in a dedicated "Diagrams" section at the end, not inline)

    _C_SUN = ["Repo", "API", "Status", "Retires", "Call-sites", "First call-site"]
    _C_EOL = ["Repo", "Component", "Status", "EOL", "Call-sites", "First call-site"]
    _C_CVE = ["Repo", "Package", "Status", "Fix", "Call-sites", "First call-site"]
    # each queue is the work ONE team owns; sub-categories keep the kind-specific columns.
    # The eol split mirrors owners.owner(): refKind runtime -> DevOps, else Developer, so no
    # eol action can fall between the two tables.
    queues = (
        ("devops", "DevOps queue — packages & runtimes", (
            ("Package vulnerabilities", _C_CVE, lambda a: a.get("kind") == "cve", False),
            ("Runtime end-of-life", _C_EOL,
             lambda a: a.get("kind") == "eol" and a.get("refKind") == "runtime", False),
        )),
        ("developer", "Developer queue — vendor APIs & frameworks", (
            ("Vendor API sunsets", _C_SUN, lambda a: a.get("kind") == "sunset", True),
            ("Framework end-of-life", _C_EOL,
             lambda a: a.get("kind") == "eol" and a.get("refKind") != "runtime", False),
        )),
    )
    for owner_key, qtitle, cats in queues:
        # honour the stored owner (a verified field); derive it only if a caller handed us
        # an action without one, so the renderer never silently drops a job
        q_actions = [a for a in actions if (a.get("owner") or owners.owner(a)) == owner_key]
        if not q_actions:
            continue
        L.append(f"## {qtitle}")
        L.append("")
        for ctitle, cols, pred, is_sunset in cats:
            group = [a for a in q_actions if pred(a)]
            if not group:
                continue
            L.append(f"### {ctitle}")
            L.append("")
            _render_group(group, cols, is_sunset)

    # --- coverage: shape + catalog verdicts (sentences + a table) ---
    grades = payload.get("coverageGrades", [])
    catalog = payload.get("catalog", [])
    if grades or catalog:
        L.append("## Coverage — what the scan is sure of")
        L.append("")
    if grades:
        L.append("**Per-repo (can we see the calls?)**")
        L.append("")
        L += _table(["Repo", "Grade", "Attributed", "Unattributed paths", "Unresolved sinks"],
                    [[g.get("repoLabel") or g.get("repo"), g.get("grade"), g.get("attributed"),
                      g.get("unattributedPaths"), g.get("unresolvedSinks")] for g in grades])
        L.append("")
    if catalog:
        L.append("**Per-vendor (have we checked the retirement list?)**")
        L.append("")
        L += _table(["Vendor", "Verdict", "Call-sites", "Catalog entries", "Checked"],
                    [[c.get("vendor"), c.get("verdict"), c.get("callSites"),
                      c.get("catalogEntries"), c.get("checked") or "never"] for c in catalog])
        L.append("")

    # --- notes (coverage caveats, plain-folder warnings, unaudited disclosures) ---
    notes = payload.get("coverageNotes", [])
    if notes:
        L.append("## Notes")
        L.append("")
        for nte in notes:
            L.append(f"- {_esc(nte)}")
        L.append("")

    # --- diagrams: a segmented visual gallery, AFTER the report ---
    L.extend(_diagrams(actions, now))

    L.append("---")
    L.append("_Rendered from `drift.json` — deterministic, 0 LLM tokens, every date sourced._")
    return "\n".join(L) + "\n"

"""Turn drift.json findings into GitLab issues, idempotently, per repo, per audience.

The delivery is a PROJECTION of the verified payload, so it only ever runs after a green
`verify`. Two audiences (agent/lib/owners.py), each flagged repo gets ONE comprehensive
issue per audience, filed IN that repo's own project (not a central one), assigned:
  • DevOps actions (packages + runtime EOL) -> one issue per repo, assigned to the
    configured DevOps account.
  • Developer actions (vendor API sunsets + framework EOL) -> one issue per repo, assigned
    to the resolved repo owner (`resolve_owner`).
The draft-merge-request path is retired — `plan["mrs"]` is always `[]` for findings (the
`mr_*` helpers and `execute_plan`'s MR loop remain only for any pre-existing MRs already in
flight; nothing new is ever planned there).

Idempotency is the whole game — a re-scan must UPDATE, never duplicate. Issues carry a hidden
marker `<!-- drift-detector:<fp> -->` (namespaced per repo+audience via `repo_fingerprint`)
and a `drift-detector` label plus an audience label (`drift:devops` / `drift:developer`).
`build_plan` is PURE (payload + what already exists -> the create/update/close plan), so it
is testable without any network.
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse

LABEL = "drift-detector"
DEVOPS_LABEL = "drift:devops"
DEVELOPER_LABEL = "drift:developer"
# MAINTAINER audience (tool/catalog upkeep) — carried ALONGSIDE a stream label so all
# maintainer work filters as one queue, while shape vs freshness stay distinguishable.
MAINTAINER_LABEL = "drift:maintainer"
SHAPE_LABEL = "drift:shape"           # absorption: a repo shape the scanner can't read
FRESHNESS_LABEL = "drift:freshness"   # a catalogued vendor's retirements went stale / need a re-check
MR_BRANCH = "drift/migrations"
MIGRATIONS_PATH = ".drift/MIGRATIONS.md"
_MARKER = re.compile(r"<!--\s*drift-detector:([0-9a-f]{16})\s*-->")


def _sunset_unit(a: dict) -> str:
    return a.get("unit") or ""


def action_fingerprint(a: dict) -> str:
    """Stable, version-INDEPENDENT identity of a job: (repo, kind, ref, retiring-unit). A
    version bump updates the same issue instead of spawning a sibling."""
    raw = f"{a.get('repo')}|{a.get('kind')}|{a.get('ref')}|{_sunset_unit(a)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def resolve_owner(members: list, fallback_id):
    """The repo owner to assign a Developer issue to: highest GitLab access_level (Owner=50 >
    Maintainer=40), ties broken by lowest id (deterministic), else the config fallback, else None
    (unassigned). Pure — the members list is fetched by the caller."""
    eligible = [m for m in members if (m.get("access_level") or 0) >= 40]   # Maintainer+
    if eligible:
        best = min(eligible, key=lambda m: (-(m.get("access_level") or 0), m.get("id", 1 << 62)))
        return best.get("id")
    return fallback_id


def repo_fingerprint(repo: str, stream: str = "") -> str:
    raw = f"repo|{stream}|{repo}" if stream else f"repo|{repo}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def vendor_fingerprint(repo: str, vendor: str, stream: str) -> str:
    """Identity for a per-vendor issue: (audience stream, repo, vendor) — distinct namespace
    from repo/action/shape/freshness so a granularity switch never collides fingerprints."""
    raw = f"vendor|{stream}|{repo}|{vendor}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def shape_fingerprint(repo: str) -> str:
    """Repo-keyed identity for an absorption flag: ONE issue per repo that UPDATES in place as
    the residue drifts (a new residueFingerprint rewrites the body, the marker stays), rather
    than a sibling per code change. Distinct namespace from repo_fingerprint / action_fingerprint."""
    return hashlib.sha256(f"shape|{repo}".encode()).hexdigest()[:16]


def freshness_fingerprint() -> str:
    """Constant identity for THE catalog-freshness work-order: one issue for the whole catalog
    (the work-order is one maintainer queue, not an issue per vendor) that updates in place as
    vendors go stale/current and closes itself via `_finish` when nothing is due."""
    return hashlib.sha256(b"freshness|catalog").hexdigest()[:16]


def marker(fp: str) -> str:
    return f"<!-- drift-detector:{fp} -->"


def markers_in(text: str) -> set:
    return set(_MARKER.findall(text or ""))


def project_path(remote_url: str) -> str | None:
    """`https://host/group/repo` -> `group/repo`; None if unparseable."""
    m = re.match(r"^https?://[^/]+/(.+?)(?:\.git)?/?$", str(remote_url or ""))
    return m.group(1) if m else None


def _label_of(a: dict) -> str:
    return a.get("ref", "") + (f" {a['unit']}" if a.get("unit") else "")


def _when(a: dict) -> str:
    d = a.get("date")
    if not d:
        return a.get("fix_version") or ""
    return d


_EMOJI_ORDER = ("🚨", "☣️", "🛡️", "⏳", "⚠️")


def _emoji(a: dict) -> str:
    """A leading urgency glyph so a drift issue stands out in a crowded tracker AND encodes
    state at a glance, without reading the body. Pure function of already-computed fields
    (status/kind/worst) — no wall-clock, no date-math here (the pipeline already resolved
    past-due-ness into `status`)."""
    if a.get("kind") == "sunset":
        return "🚨" if (a.get("status") == "DEPRECATED" and a.get("date")) else "⏳"
    if a.get("kind") == "eol":
        return "☣️"
    if a.get("worst") == "CRITICAL":
        return "🛡️"
    return "⚠️"


def _emoji_worst(acts: list) -> str:
    """The most urgent emoji among a group of actions, so a comprehensive/per-vendor issue's
    title reflects its worst-case content."""
    present = {_emoji(a) for a in acts}
    for e in _EMOJI_ORDER:
        if e in present:
            return e
    return "⚠️"


def _sites_md(a: dict) -> list:
    lines = []
    for f in (a.get("files") or [])[:12]:
        loc = f.get("loc") if isinstance(f, dict) else str(f)
        href = f.get("href") if isinstance(f, dict) else None
        lines.append(f"  - [`{loc}`]({href})" if href else f"  - `{loc}`")
    return lines


# ------------------------------------------------------------------ issue bodies (DevOps)
def issue_title(a: dict) -> str:
    when = _when(a)
    tail = f" — by {when}" if when else ""
    return f"{_emoji(a)} [drift] {_label_of(a)}{tail}"


# ---------------------------------------------------------------- "Open in Claude" deep-links
# A one-click hand-off: the reader opens Claude Code on the web (claude.ai/code) with the finding
# already in the prompt, so Claude has the full picture — the dying API, its call-sites, the dated
# retirement, the recommended migration — without the human retyping any of it. The fleet repos
# live on GitLab (not GitHub), so we pass the context IN the prompt rather than auto-connecting a
# repo (the `repositories=` param only wires GitHub). The URL scheme is intentionally isolated in
# these two helpers so it is a one-line change if claude.ai's deep-link format evolves.
_CLAUDE_BASE = "https://claude.ai/code?prompt="


def _claude_prompt(a: dict, display: str | None = None) -> str:
    when = _when(a)
    lines = ["Help me migrate off a dying third-party API that Drift Detector flagged.", "",
             f"- API: {_label_of(a)}",
             f"- Status: {a.get('status')}" + (f" — {when}" if when else ""),
             f"- Repo: {display or a.get('repo')}"]
    if a.get("recommendation"):
        lines.append(f"- Recommendation: {a['recommendation']}")
    sites = [f.get("loc") if isinstance(f, dict) else str(f) for f in (a.get("files") or [])[:12]]
    if sites:
        lines.append("- Call-sites:")
        lines += [f"  - {s}" for s in sites]
    if a.get("sources"):
        lines.append("- Source: " + ", ".join(a["sources"]))
    lines += ["", "Explain what's changing and the blast radius, then give me a step-by-step "
              "migration plan for these call-sites."]
    return "\n".join(lines)


def _claude_url(a: dict, display: str | None = None) -> str:
    return _CLAUDE_BASE + urllib.parse.quote(_claude_prompt(a, display))


def _claude_prompt_repo(repo: str, actions: list) -> str:
    lines = [f"Help me address the dying third-party API integrations Drift Detector flagged "
             f"in {repo}.", ""]
    for a in actions[:20]:
        when = _when(a)
        lines.append(f"- {_label_of(a)} — {a.get('status')}" + (f", {when}" if when else ""))
    lines += ["", "Give me a prioritized migration plan across these findings, worst-first."]
    return "\n".join(lines)


def _claude_url_repo(repo: str, actions: list) -> str:
    return _CLAUDE_BASE + urllib.parse.quote(_claude_prompt_repo(repo, actions))


def _footer(links: dict | None = None, *, draft: bool = False, claude_url: str | None = None) -> str:
    """The provenance + hand-off line: 'Open in Claude' (the finding, pre-loaded into Claude Code),
    the public Cockpit (the shareable GitHub Pages report — the main surface now), and the scan run
    that filed it (traceability). `links['report']` is the Cockpit URL; `links['run']` the CI run."""
    parts = ["Draft, filed by Drift Detector" if draft else "Filed by Drift Detector"]
    if claude_url:
        parts.append(f"🤖 [Open in Claude]({claude_url})")
    if links:
        if links.get("report"):
            parts.append(f"📊 [open the cockpit]({links['report']})")
        if links.get("run"):
            parts.append(f"[scan run]({links['run']})")
    return "_" + " · ".join(parts) + " — updates in place on the next scan._"


def issue_body(a: dict, display: str | None = None, links: dict | None = None) -> str:
    fp = action_fingerprint(a)
    lines = [marker(fp), "",
             f"**{_label_of(a)}** in `{display or a.get('repo')}` — {a.get('status')}", ""]
    if a.get("recommendation"):
        lines += [f"➡️ {a['recommendation']}", ""]
    if a.get("command"):
        lines += [f"```\n{a['command']}\n```", ""]
    sites = _sites_md(a)
    if sites:
        lines += ["Call-sites:", *sites, ""]
    if a.get("sources"):
        lines += ["Source(s): " + ", ".join(a["sources"]), ""]
    lines += [_footer(links, claude_url=_claude_url(a, display))]
    return "\n".join(lines)


# ----------------------------------------------------- absorption flags (shape stream, maintainer)
def shape_issue_title(shape: dict, display: str | None = None) -> str:
    n = shape.get("unattributedPaths", 0)
    reasons = ", ".join(shape.get("reasons", [])) or "unreadable shape"
    return (f"[drift] absorption needed: {display or shape.get('repo')} "
            f"— {n} unattributed path(s) ({reasons})")


def shape_issue_body(shape: dict, display: str | None = None,
                     samples: list | None = None, links: dict | None = None) -> str:
    """A maintainer-facing flag: this repo has a shape the scanner can't fully read. Carries
    the WHY (verdict + reasons), the exact blind-spot file:lines, the residueFingerprint (the
    token the resolving MR cites), and the bootstrap to absorb it. This is NOT a finding — it's
    a request to teach the scanner. Closes itself once the repo goes KNOWN (see _finish)."""
    fp = shape_fingerprint(shape.get("repo"))
    langs = ", ".join((shape.get("languages") or {}).keys())
    lines = [marker(fp), "",
             f"**Absorption needed** — `{display or shape.get('repo')}` came back "
             f"**{shape.get('verdict')}**: the deterministic scanner could not fully read its "
             f"integration calls, so its findings are incomplete (“cannot see” is not "
             f"“clean”).", "",
             f"- **Why:** {', '.join(shape.get('reasons', [])) or 'unreadable shape'}",
             f"- **Languages:** {langs or '?'}",
             f"- **Attributed / unattributed:** {shape.get('attributed', 0)} attributed · "
             f"{shape.get('unattributedPaths', 0)} path(s) + {shape.get('unresolvedSinks', 0)} "
             f"sink(s) unread",
             f"- **Residue fingerprint:** `{shape.get('residueFingerprint', '')}` "
             f"_(the absorption MR that resolves this should cite it)_", ""]
    caps = (samples or [])[:12]
    if caps:
        lines.append("**Blind spots** — versioned paths seen but not attributed:")
        for s in caps:
            loc, samp = s.get("loc"), s.get("sample")
            lines.append(f"  - `{loc}` — `{samp}`" if samp else f"  - `{loc}`")
        if len(samples) > 12:
            lines.append(f"  - …and {len(samples) - 12} more (see the report)")
        lines.append("")
    lines += ["**To absorb this shape** (a maintainer with access to the flagged repo):",
              "```",
              "git clone <the flagged repo> && cd <repo>",
              "export DRIFT_OPS_DIR=<your drift-ops checkout>   # where the learned overlay lives",
              "/drift-detector .        # scan it locally",
              "/drift-absorb .          # investigate the blind spots, teach the scanner",
              "```",
              "_The absorbed idioms/sunsets land as a reviewed MR on drift-ops; the next fleet "
              "scan then sees this repo KNOWN and closes this issue on its own._", "",
              _footer(links)]
    return "\n".join(lines)


# --------------------------------------------------------------- MR content (Developer)
def migrations_md(repo: str, actions: list, links: dict | None = None) -> str:
    fp = repo_fingerprint(repo, "developer")
    out = ["# API migrations — Drift Detector", "",
           "Retiring vendor APIs / end-of-life frameworks this repo calls. Do the migration "
           "on this branch; this checklist is regenerated each scan.", "", marker(fp), ""]
    for a in actions:
        out.append(f"## {_label_of(a)} — {a.get('status')}"
                   + (f" · retires {a['date']}" if a.get("date") else ""))
        if a.get("recommendation"):
            out.append(a["recommendation"])
        sites = _sites_md(a)
        if sites:
            out += ["", "Call-sites:", *sites]
        if a.get("sources"):
            out.append("Source(s): " + ", ".join(a["sources"]))
        out.append("")
    out.append(_footer(links, claude_url=_claude_url_repo(repo, actions)))
    return "\n".join(out)


def devops_repo_body(repo: str, actions: list, links: dict | None = None) -> str:
    """Per-repo DevOps issue body: bundles package vulnerabilities and runtime EOL findings,
    idempotent via marker. Mirrors migrations_md but for DevOps stream."""
    fp = repo_fingerprint(repo, "devops")
    out = ["# Platform upkeep — Drift Detector", "",
           "Package vulnerabilities and runtime end-of-life for this repo. Bump the "
           "manifest/lockfile or base image; this list is regenerated each scan.", "",
           marker(fp), ""]
    for a in actions:
        out.append(f"## {_label_of(a)} — {a.get('status')}"
                   + (f" · retires {a['date']}" if a.get("date") else ""))
        if a.get("recommendation"):
            out.append(a["recommendation"])
        if a.get("cves"):
            out += ["", "CVEs: " + ", ".join(str(c.get("id")) for c in a["cves"])]
        if a.get("sources"):
            out.append("Source(s): " + ", ".join(a["sources"]))
        out.append("")
    out.append(_footer(links, claude_url=_claude_url_repo(repo, actions)))
    return "\n".join(out)


def mr_title(repo: str) -> str:
    return f"Draft: [drift] API migrations for {repo}"


def mr_description(repo: str, actions: list, links: dict | None = None) -> str:
    fp = repo_fingerprint(repo)
    n = len(actions)
    lines = [marker(fp), "",
             f"Drift Detector found **{n}** retiring API surface(s) / EOL framework(s) this "
             f"repo calls. The checklist is in `{MIGRATIONS_PATH}` on this branch; migrate "
             f"here and this draft becomes your fix.", ""]
    for a in actions:
        when = f" (retires {a['date']})" if a.get("date") else ""
        lines.append(f"- **{_label_of(a)}**{when} — {a.get('recommendation') or a.get('status')}")
    lines += ["", _footer(links, draft=True)]
    return "\n".join(lines)


def _norm(s: str) -> str:
    """Normalise for the change-check: GitLab returns descriptions with CRLF and can trim
    trailing whitespace, so a raw compare against our LF body always looks 'changed' and the
    issue gets rewritten every run (noise, notifications). Compare on normalised text so an
    unchanged issue truly SKIPS."""
    return "\n".join(line.rstrip() for line in
                     str(s or "").replace("\r\n", "\n").split("\n")).strip()


def _issue_op(fp: str, title: str, body: str, by_fp: dict, project: str, *,
             assignee=None) -> dict:
    """create / update / skip / reopen an issue by its marker fingerprint."""
    iss = by_fp.get(fp)
    if iss is None:
        return {"op": "create", "fp": fp, "project": project, "title": title, "body": body,
                "assignee": assignee}
    changed = (_norm(iss.get("description")) != _norm(body)) or (iss.get("state") == "closed")
    return {"op": "update" if changed else "skip", "fp": fp, "project": project,
            "iid": iss.get("iid"), "title": title, "body": body, "assignee": assignee,
            "reopen": iss.get("state") == "closed"}


# ----------------------------------------------------------------------- the planner (pure)
def _audience_ops(acts: list, audience: str, title_word: str, body_fn, repo_meta: dict,
                  assignees: dict, links: dict | None, granularity: str, by_fp: dict,
                  live_fps: set, issue_plan: list) -> None:
    """Build + append the issue ops for one audience (devops/developer) under the chosen
    granularity, mutating `issue_plan`/`live_fps` in place (mirrors the shape/freshness blocks
    around it). `body_fn(project, acts, links)` renders the comprehensive/per-vendor body —
    `devops_repo_body` and `migrations_md` share that signature."""
    def assignee_for(repo):
        if audience == "devops":
            return assignees.get("devops")
        return (assignees.get("developer") or {}).get(repo)

    by_repo: dict = {}
    for a in acts:
        by_repo.setdefault(a.get("repo"), []).append(a)

    if granularity == "per-problem":
        for a in acts:
            repo = a.get("repo")
            project = (repo_meta.get(repo) or {}).get("project") or repo
            fp = action_fingerprint(a)
            live_fps.add(fp)
            op = _issue_op(fp, issue_title(a), issue_body(a, project, links), by_fp, project,
                          assignee=assignee_for(repo))
            op["stream"] = audience
            issue_plan.append(op)
        return

    if granularity == "per-vendor":
        for repo, repo_acts in by_repo.items():
            project = (repo_meta.get(repo) or {}).get("project") or repo
            by_vendor: dict = {}
            for a in repo_acts:
                by_vendor.setdefault(a.get("ref"), []).append(a)
            for vendor, v_acts in by_vendor.items():
                fp = vendor_fingerprint(project, vendor, audience)
                live_fps.add(fp)
                op = _issue_op(fp, f"{_emoji_worst(v_acts)} [drift] {vendor} — {project}",
                              body_fn(project, v_acts, links), by_fp, project,
                              assignee=assignee_for(repo))
                op["stream"] = audience
                issue_plan.append(op)
        return

    # comprehensive (default): ONE issue per repo, byte-identical to pre-granularity behaviour
    # except the leading emoji.
    for repo, repo_acts in by_repo.items():
        project = (repo_meta.get(repo) or {}).get("project") or repo
        fp = repo_fingerprint(project, audience)
        live_fps.add(fp)
        op = _issue_op(fp, f"{_emoji_worst(repo_acts)} [drift] {title_word} {project}",
                      body_fn(project, repo_acts, links), by_fp, project,
                      assignee=assignee_for(repo))
        op["stream"] = audience
        issue_plan.append(op)


def build_plan(payload: dict, repo_meta: dict, existing: dict, devops_project: str,
               *, dev_as_issues: bool = False, links: dict | None = None,
               shape_stream: bool = False, freshness_stream: bool = False,
               assignees: dict | None = None,
               granularity: str = "comprehensive") -> dict:
    """Compute the create/update/close plan. PURE: no I/O.

    `repo_meta`   : {repo -> {"project": "group/repo"}} for the scanned repos.
    `existing`    : {"issues": [issue dicts, from wherever they were fetched],
                     "mrs": {project -> [mr dicts]}} already on GitLab.
    `assignees`   : {"devops": id|None, "developer": {repo: id|None}} — pre-resolved GitLab
                    user ids (`resolve_owner`, `gl.user_id`), threaded straight onto each op.
    `dev_as_issues`: accepted for back-compat, otherwise IGNORED — findings are always filed
                    as in-repo issues now (the draft-MR path is retired; see module docstring).
    `shape_stream`: also file a MAINTAINER-facing "absorption needed" issue (one per repo) for
                    every UNKNOWN shape in the payload — the repo has integration calls the
                    scanner could not read. Repo-keyed, updates in place, and closes itself via
                    `_finish` once the repo goes KNOWN.
    `freshness_stream`: also file THE maintainer catalog-freshness work-order (one issue for
                    the whole catalog) while any DETECTED vendor is STALE/unaudited and off the
                    auto lane — the drift:freshness label's producer. Constant-keyed, updates
                    in place, closes itself via `_finish` when the due-list empties.
    `granularity` : how the DevOps/Developer audiences split into issues — "comprehensive"
                    (default, one issue per repo per audience), "per-problem" (one issue per
                    action, keyed by `action_fingerprint`), or "per-vendor" (one issue per
                    (repo, `ref`) per audience, keyed by `vendor_fingerprint`). Does not affect
                    the shape/freshness maintainer streams. See `_audience_ops`.
    Returns {"issues": [...], "mrs": []} where each item has an `op`
    (create|update|close|skip) and the rendered content. `mrs` is always empty for findings.
    """
    # `granularity` ("comprehensive" | "per-problem" | "per-vendor") governs how the DevOps and
    # Developer audiences are split into issues — see `_audience_ops`. It does not touch the
    # shape/freshness maintainer streams below.
    assignees = assignees or {"devops": None, "developer": {}}
    actions = payload.get("actions", [])
    devops = [a for a in actions if a.get("owner") == "devops"]
    developer = [a for a in actions if a.get("owner") == "developer"]

    existing_issues = existing.get("issues", [])
    by_fp = {}
    for iss in existing_issues:
        for fp in markers_in(iss.get("description", "")):
            by_fp[fp] = iss
    issue_plan, live_fps = [], set()

    # ---- DevOps: filed IN the repo, assigned to the DevOps account ----
    _audience_ops(devops, "devops", "platform upkeep for", devops_repo_body, repo_meta,
                 assignees, links, granularity, by_fp, live_fps, issue_plan)

    # ---- absorption flags (maintainer: one per UNKNOWN shape) ----
    # Placed before the dev branch so it lands in issue_plan + live_fps for BOTH return paths;
    # a repo that goes KNOWN drops out of live_fps and _finish closes its flag automatically.
    if shape_stream:
        samples_by_repo: dict = {}
        for s in payload.get("residueSamples", []):
            samples_by_repo.setdefault(s.get("repo"), []).append(s)
        for sh in payload.get("shapes", []):
            if sh.get("verdict") != "UNKNOWN":
                continue
            repo = sh.get("repo")
            fp = shape_fingerprint(repo)
            live_fps.add(fp)
            display = (repo_meta.get(repo) or {}).get("project") or sh.get("repoLabel") or repo
            op = _issue_op(fp, shape_issue_title(sh, display),
                           shape_issue_body(sh, display, samples_by_repo.get(repo), links),
                           by_fp, devops_project)
            op["stream"] = "shape"          # so execute_plan labels it drift:shape
            issue_plan.append(op)

    # ---- freshness work-order (maintainer: ONE issue while any vendor is due) ----
    # The human-lane twin of catalog-check, DELIVERED: which detected vendors' retirement
    # audit is STALE or never done and no machine can re-fetch their source, with the right
    # action per vendor (freshness.work_order_md — the same body `drift-scan freshness`
    # renders). Until this block existed the drift:freshness label had a taxonomy and an
    # execute_plan branch but no producer — the due-list lived only in a CLI nobody was
    # required to run. Placed with the shape block so it lands in live_fps for both return
    # paths; an emptied due-list drops the fp and _finish closes the work-order on its own.
    if freshness_stream:
        from agent import catalog_check
        from agent.lib import freshness as freshness_mod
        due = freshness_mod.due_for_refresh(payload.get("catalog", []),
                                            set(catalog_check.CHECKS),
                                            catalog_check.UNAUTOMATED)
        if due:
            fp = freshness_fingerprint()
            live_fps.add(fp)
            # `generated` (the scan date in the payload) — never wall-clock — keeps the
            # body a pure function of the payload, so an unchanged due-list SKIPS.
            body = (marker(fp) + "\n\n"
                    + freshness_mod.work_order_md(due, payload.get("generated", "")))
            op = _issue_op(fp, f"[drift] catalog freshness: {len(due)} vendor(s) due a re-check",
                           body, by_fp, devops_project)
            op["stream"] = "freshness"      # so execute_plan labels it drift:freshness
            issue_plan.append(op)

    # ---- Developer: filed IN the repo, assigned to the resolved repo owner ----
    _audience_ops(developer, "developer", "API migrations for", migrations_md, repo_meta,
                 assignees, links, granularity, by_fp, live_fps, issue_plan)

    return _finish(issue_plan, [], by_fp, live_fps, devops_project)


def _finish(issue_plan, mr_plan, by_fp, live_fps, devops_project) -> dict:
    """Close issues we filed whose fingerprint is no longer among the findings — a resolved
    finding must not leave a stale open issue (the human 'cannot see = clean' trap)."""
    for fp, iss in by_fp.items():
        if fp not in live_fps and iss.get("state") != "closed":
            issue_plan.append({"op": "close", "fp": fp,
                               "project": iss.get("project_id") or devops_project,
                               "iid": iss.get("iid"), "title": iss.get("title")})
    return {"issues": issue_plan, "mrs": mr_plan}


# The dry-run views group issues by the SAME audience/stream split delivery uses, so a reader
# sees the two per-repo streams (and the maintainer streams) distinctly. A close op carries no
# stream (it's a resolved finding dropping out) → shown under "closing".
_STREAM_HEAD = {"devops": "DevOps issues", "developer": "Developer issues",
                "shape": "Maintainer · absorption", "freshness": "Maintainer · catalog freshness",
                "closing": "Closing (resolved)"}
_STREAM_ORDER = ("devops", "developer", "shape", "freshness", "closing")


def _by_stream(issues: list) -> dict:
    out: dict = {}
    for it in issues:
        out.setdefault(it.get("stream") or "closing", []).append(it)
    return out


def plan_summary(plan: dict) -> str:
    def tally(items):
        c = {}
        for it in items:
            c[it["op"]] = c.get(it["op"], 0) + 1
        return ", ".join(f"{v} {k}" for k, v in sorted(c.items())) or "nothing"
    grouped = _by_stream(plan["issues"])
    lines = [f"issues: {tally(plan['issues'])}"]
    for s in _STREAM_ORDER:
        if grouped.get(s):
            lines.append(f"  {s}: {tally(grouped[s])}")
    return "\n".join(lines)


def plan_detail(plan: dict) -> str:
    """A human-readable, line-per-item view for --dry-run, grouped by audience/stream."""
    grouped = _by_stream(plan["issues"])
    lines = []
    for s in _STREAM_ORDER:
        items = grouped.get(s)
        if not items:
            continue
        head = _STREAM_HEAD[s]
        lines.append(f"── {head} " + "─" * max(4, 44 - len(head)))
        for it in items:
            loc = f"#{it['iid']}" if it.get("iid") else "new"
            who = f"  @{it['assignee']}" if it.get("assignee") else ""
            lines.append(f"  {it['op']:7} [{loc}] {it.get('title', '')}  → {it['project']}{who}")
    return "\n".join(lines) or "(nothing to deliver)"


# ------------------------------------------------------------------------------- I/O
def fetch_existing(gl, devops_project: str, dev_projects: list) -> dict:
    """What drift-detector has already filed: labelled issues in the DevOps project (the
    still-central maintainer streams: shape, freshness) UNION each dev project's own tracker
    (the in-repo DevOps/Developer issues, Task 3) — every issue that build_plan could match a
    fingerprint against. Read-only — safe in --dry-run.

    Returns the RAW issue dicts from `list_issues`, `project_id` and all: `_finish` reads
    `iss.get("project_id")` to close a stale in-repo issue at its OWN project rather than
    devops_project, so nothing here may strip or copy fields off them."""
    issues = list(gl.list_issues(devops_project, labels=LABEL))
    for p in dev_projects:
        issues += gl.list_issues(p, labels=LABEL)
    # findings no longer produce MRs, and nothing reads existing["mrs"] — so don't spend a
    # list_mrs call per repo every run. (Legacy in-flight drift/migrations MRs are swept by hand.)
    return {"issues": issues, "mrs": {}}


def _issue_labels(stream: str) -> str:
    """The label set for an issue by stream. Maintainer streams (shape, freshness) carry the
    shared `drift:maintainer` audience tag AND their own stream tag, so all tool-upkeep work
    filters as one queue while staying distinguishable; the DevOps finding stream stands alone."""
    if stream == "shape":
        return f"{LABEL},{MAINTAINER_LABEL},{SHAPE_LABEL}"
    if stream == "freshness":
        return f"{LABEL},{MAINTAINER_LABEL},{FRESHNESS_LABEL}"
    if stream == "developer":
        return f"{LABEL},{DEVELOPER_LABEL}"
    return f"{LABEL},{DEVOPS_LABEL}"


def execute_plan(gl, plan: dict) -> dict:
    """Perform the writes. Every op is idempotent given the same plan.

    Each issue op is wrapped in its own try/except: one repo's write failing (permissions,
    a renamed project, a transient GitLab error) must not abort the rest of the fleet's issues
    — "cannot see" is never "clean", so a failure is collected into `done["failed"]`
    (`(project, reason)` pairs) and REPORTED, never silently dropped."""
    done = {"created": 0, "updated": 0, "closed": 0, "skipped": 0, "unroutable": 0, "failed": []}
    for it in plan["issues"]:
        aid = [it["assignee"]] if it.get("assignee") else None
        try:
            if it["op"] == "create":
                gl.create_issue(it["project"], title=it["title"], description=it["body"],
                                labels=_issue_labels(it.get("stream")), assignee_ids=aid)
                done["created"] += 1
            elif it["op"] == "update":
                fields = {"description": it["body"], "title": it["title"]}
                if aid:
                    fields["assignee_ids"] = aid
                if it.get("reopen"):
                    fields["state_event"] = "reopen"
                gl.update_issue(it["project"], it["iid"], **fields)
                done["updated"] += 1
            elif it["op"] == "close":
                gl.update_issue(it["project"], it["iid"], state_event="close")
                done["closed"] += 1
            else:
                done["skipped"] += 1
        except Exception as exc:                     # a failed file is REPORTED, never dropped
            done["failed"].append((it.get("project"), str(exc)))
    for it in plan["mrs"]:
        if it["op"] == "unroutable":
            done["unroutable"] += 1
            continue
        project, branch = it["project"], it["branch"]
        default = (gl.project(project) or {}).get("default_branch") or "main"
        if gl.branch(project, branch) is None:
            gl.create_branch(project, branch, default)
        existing_file = gl.get_file(project, it["file_path"], branch)
        gl.set_file(project, it["file_path"], branch=branch, content=it["file_content"],
                    message="drift: update migration checklist",
                    exists=existing_file is not None)
        if it["op"] == "create":
            gl.create_mr(project, source_branch=branch, target_branch=default,
                         title=it["title"], description=it["description"],
                         labels=f"{LABEL},{DEVELOPER_LABEL}")
            done["created"] += 1
        else:
            gl.update_mr(project, it["iid"], description=it["description"], title=it["title"])
            done["updated"] += 1
    return done

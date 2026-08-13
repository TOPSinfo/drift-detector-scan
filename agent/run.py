"""The deterministic scan -> audit -> deliver pipeline, in one non-interactive call.

This is what the cron job runs (zero LLM tokens). All external effects — the scan engine,
git, HTTP — are injected, so tests exercise the whole pipeline without network or a real engine.
"""
from __future__ import annotations

import json
import os
import subprocess

from agent.inventory_scan import scan_folder
from agent.audit import audit_inventory
from agent import resolve as resolve_mod
from agent.lib.chart_render import render_chart
from agent.lib.dashboard_render import build_payload, build_bundle, render_payload
from agent.lib.md_render import render_markdown
from agent.lib.summary_render import render_summary
from agent.lib.findings_state import apply_lifecycle
from agent.lib.repo_discovery import discover_repos
from agent.lib.http_util import default_http


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _default_pull(repo_path):
    subprocess.run(["git", "-C", repo_path, "pull", "--ff-only"],
                   capture_output=True, timeout=120)


def _pull_repos(roots, pull_run):
    runner = pull_run or _default_pull
    for abs_path, _identity in discover_repos(roots):
        try:
            runner(abs_path)
        except Exception:
            pass          # best-effort; a repo that won't fast-forward is scanned as-is


def _apply_resolution(verdicts, now) -> dict:
    """Gate + apply a resolution-pass verdict batch. Never raises: a rejected or otherwise
    broken batch degrades to a `{"status": ...}` note rather than blocking the deterministic
    report (docs/superpowers/specs/2026-08-13-no-queue-design.md, "A failed AI pass must
    degrade, not block"). The caller decides whether to re-scan from the `status` returned."""
    try:
        applied = resolve_mod.apply(verdicts, now=now)
    except resolve_mod.ResolveRejected as exc:
        return {"status": "rejected", "problems": list(exc.args[0])}
    except Exception as exc:   # noqa: BLE001 — any apply-time failure degrades, never blocks
        return {"status": "error", "detail": str(exc)}
    return {"status": "applied", "written": applied["written"], "needs_human": applied["needs_human"]}


def run_pipeline(roots, state_dir, now, *, pull=False,
                 engine=None, run=None, git=None, http=None, progress=None,
                 pull_run=None, gitlab_hosts=frozenset(), resolve=None) -> dict:
    roots = [roots] if isinstance(roots, (str, os.PathLike)) else list(roots)
    os.makedirs(state_dir, exist_ok=True)
    if pull:
        _pull_repos(roots, pull_run)

    scan = scan_folder(roots, state_dir, now, engine=engine, run=run, git=git, progress=progress)
    doc, diff = scan["doc"], scan["diff"]

    # No-queue resolution (docs/superpowers/specs/2026-08-13-no-queue-design.md): the AI never
    # writes the answer into drift.json, it writes evidence; `resolve.apply` gates it into
    # reviewed overlay catalog data; and — the load-bearing step — the deterministic scanner
    # RE-SCANS so drift.json comes entirely from a second, ordinary deterministic pass. If the
    # gate rejects the batch (or anything else about applying it goes wrong), nothing is
    # re-scanned and the first scan's result is what gets reported — never a half-applied
    # catalog, and never a withheld report.
    resolve_result = None
    if resolve is not None:
        resolve_result = _apply_resolution(resolve, now)
        if resolve_result["status"] == "applied":
            # Same roots/state_dir/now/engine/run/git/progress — the ONLY thing that changed
            # underfoot is the overlay catalog `apply` just wrote. This must be the identical
            # deterministic scan, not a different kind of scan.
            scan = scan_folder(roots, state_dir, now, engine=engine, run=run, git=git,
                               progress=progress)
            doc, diff = scan["doc"], scan["diff"]

    _write_json(os.path.join(state_dir, "inventory.json"), doc)

    audit = audit_inventory(doc, now, http=http) if http else audit_inventory(doc, now)
    apply_lifecycle(audit, state_dir, now)
    _write_json(os.path.join(state_dir, "audit.json"), audit)
    # ONE payload, five sinks that cannot disagree:
    #   drift.json     the canonical machine-readable report (the "spec")
    #   drift.md       the primary, agent-readable view (a verified projection)
    #   summary.html   the default HUMAN view: coverage tree + glossary + headline numbers,
    #                  no JavaScript — readable in seconds, unlike the cockpit below
    #   dashboard.html a self-contained viewer (embeds the same payload, offline/CDN-free)
    #   chart.html     an ONLINE chart view — same embedded payload, Chart.js from a CDN
    payload = build_payload(doc, audit, diff=diff, gitlab_hosts=gitlab_hosts)
    _write_json(os.path.join(state_dir, "drift.json"), payload)
    _write(os.path.join(state_dir, "drift.md"), render_markdown(payload, now))
    _write(os.path.join(state_dir, "summary.html"), render_summary(payload, now))
    # AI tiers (all optional): if a pass wrote its document into this state, surface it in the AI
    # Frontier tab. Each rides as its OWN blob so the certified drift-data stays byte-identical —
    # the mechanical proof the AI tiers cannot touch the certified one.
    def _optional(name):
        path = os.path.join(state_dir, name)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None          # OSError: file I/O; ValueError: json.JSONDecodeError + UnicodeDecodeError;
                                 # an unreadable AI blob hides its tier; it never fails the scan

    _write(os.path.join(state_dir, "dashboard.html"),
           render_payload(payload, now, bundle=build_bundle(doc, audit, now),
                          adhoc=_optional("adhoc.json"),
                          leads=_optional("leads.json"),
                          research=_optional("research.json")))
    _write(os.path.join(state_dir, "chart.html"), render_chart(payload, now))

    return {"scope": doc.get("scope", {}), "auditCounts": audit["counts"],
            # the CANONICAL, post-dedup counts the report shows (drift.json → counts). The banner
            # must print THESE, not the raw per-finding audit counts, or the first number a user
            # sees (and the one `verify` does not cover) contradicts the report.
            "counts": payload.get("counts", {}),
            "coverage": audit.get("coverage", {}),
            # from the SCAN, not the audit — why any root yielded no repo
            "rootsUnscannable": (doc.get("coverage", {}) or {}).get("rootsUnscannable", []),
            # None when --resolve wasn't passed; otherwise {"status": "applied"|"rejected"|"error", ...}
            # — see _apply_resolution. "applied" means drift.json above came from the RE-scan.
            "resolve": resolve_result}

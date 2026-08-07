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
from agent.lib.chart_render import render_chart
from agent.lib.dashboard_render import build_payload, build_bundle, render_payload
from agent.lib.md_render import render_markdown
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


def run_pipeline(roots, state_dir, now, *, pull=False,
                 engine=None, run=None, git=None, http=None, progress=None,
                 pull_run=None, gitlab_hosts=frozenset()) -> dict:
    roots = [roots] if isinstance(roots, (str, os.PathLike)) else list(roots)
    os.makedirs(state_dir, exist_ok=True)
    if pull:
        _pull_repos(roots, pull_run)

    scan = scan_folder(roots, state_dir, now, engine=engine, run=run, git=git, progress=progress)
    doc = scan["doc"]
    _write_json(os.path.join(state_dir, "inventory.json"), doc)

    audit = audit_inventory(doc, now, http=http) if http else audit_inventory(doc, now)
    apply_lifecycle(audit, state_dir, now)
    _write_json(os.path.join(state_dir, "audit.json"), audit)
    # ONE payload, four sinks that cannot disagree:
    #   drift.json     the canonical machine-readable report (the "spec")
    #   drift.md       the primary, agent-readable view (a verified projection)
    #   dashboard.html a self-contained viewer (embeds the same payload, offline/CDN-free)
    #   chart.html     an ONLINE chart view — same embedded payload, Chart.js from a CDN
    payload = build_payload(doc, audit, diff=scan["diff"], gitlab_hosts=gitlab_hosts)
    _write_json(os.path.join(state_dir, "drift.json"), payload)
    _write(os.path.join(state_dir, "drift.md"), render_markdown(payload, now))
    _write(os.path.join(state_dir, "dashboard.html"),
           render_payload(payload, now, bundle=build_bundle(doc, audit, now)))
    _write(os.path.join(state_dir, "chart.html"), render_chart(payload, now))

    return {"scope": doc.get("scope", {}), "auditCounts": audit["counts"],
            # the CANONICAL, post-dedup counts the report shows (drift.json → counts). The banner
            # must print THESE, not the raw per-finding audit counts, or the first number a user
            # sees (and the one `verify` does not cover) contradicts the report.
            "counts": payload.get("counts", {}),
            "coverage": audit.get("coverage", {}),
            # from the SCAN, not the audit — why any root yielded no repo
            "rootsUnscannable": (doc.get("coverage", {}) or {}).get("rootsUnscannable", [])}

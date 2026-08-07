"""Orchestrate one eval run: load corpus -> clone (pin-verified) -> scan+audit each repo
in-process (OSV/EOL stubbed off, so only the deterministic sunset join runs) -> score ->
render -> write under ~/.drift/eval. Seams (git, scan, audit) are injected for tests."""
from __future__ import annotations

import json
import os

from agent.inventory_scan import scan_folder
from agent.audit import audit_inventory
from agent.lib.drift_home import eval_home
from agent.eval.corpus import load_corpus
from agent.eval.clone import sync_corpus
from agent.eval.score import score
from agent.eval.render import render_scorecard

_NOOP_OSV = lambda *a, **k: []          # noqa: E731 - offline: contribute no CVEs
_NOOP_EOL = lambda *a, **k: None        # noqa: E731 - offline: contribute no EOL


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)


def run_category(category, *, now, sandbox_root, corpus_path, no_clone=False,
                 git=None, scan=None, audit=None) -> dict:
    scan = scan or scan_folder
    audit = audit or audit_inventory
    entries = [e for e in load_corpus(corpus_path) if e.get("category") == category]
    if not entries:
        raise ValueError(f"no corpus entries for category {category!r} in {corpus_path}")

    if not no_clone:
        kw = {"git": git} if git is not None else {}
        sync_corpus(entries, sandbox_root, **kw)

    cat_root = os.path.join(sandbox_root, category)
    state_dir = os.path.join(eval_home(), "runs", now, category, "_state")
    # engine=None lets scan_folder resolve the venv's ast-grep by path (resolve_engine);
    # passing a bare name would exec via PATH and fail outside an activated venv.
    scan_res = scan(cat_root, state_dir, now)
    inventory = scan_res["doc"]
    audit_doc = audit(inventory, now, osv_query=_NOOP_OSV, eol_check=_NOOP_EOL)

    sc = score(entries, inventory, audit_doc)
    sc["now"] = now

    run_dir = os.path.join(eval_home(), "runs", now, category)
    _write_json(os.path.join(run_dir, "inventory.json"), inventory)
    _write_json(os.path.join(run_dir, "audit.json"), audit_doc)
    _write_json(os.path.join(run_dir, "scorecard.json"), sc)
    hist = os.path.join(eval_home(), "scorecards", "history.jsonl")
    os.makedirs(os.path.dirname(hist), exist_ok=True)
    with open(hist, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"now": now, "category": category, "summary": sc["summary"],
                             "gate": sc["gate"]["passed"]}, sort_keys=True) + "\n")
    return sc

#!/usr/bin/env python3
"""Behavioral prompt-eval harness for the drift-detector command promptfiles.

The native `claude plugin eval` (invoke-and-grade, with an ablation baseline) is the eventual home
for this — it's gated in early access. Until it opens, this drives the REAL surface, `claude -p`,
against a set of cases, grades the output with rule checks (+ an optional haiku LLM-judge), and
prints a pass/fail score. It costs tokens and time — run it before a release, NOT in the no-network
pytest suite (which stays free/deterministic).

    python evals/run.py                    # rule graders only
    python evals/run.py --judge            # also run the haiku judge rubric (extra tokens)
    python evals/run.py --case 'research-*'  # filter by name glob

Case fields (evals/cases.yaml): name; prompt (may be a `/command …`; $EVAL_TMP expands to a scratch
dir); plugin (load the plugin dir); setup (bash run before, for fixtures); timeout; and graders —
must_contain / must_not_contain / must_not_match (regex) / judge_rubric. Exit 0 iff all selected
cases pass.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CASES = Path(__file__).resolve().parent / "cases.yaml"


def _run_claude(prompt, plugin, timeout):
    cmd = ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"]
    if plugin:
        cmd += ["--plugin-dir", str(ROOT)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return "(timed out)"


def _judge(rubric, output, timeout=120):
    prompt = ("Grade the OUTPUT against the RUBRIC. Reply with exactly PASS or FAIL on line 1, then "
              f"one short reason.\n\nRUBRIC:\n{rubric}\n\nOUTPUT:\n{output[:6000]}")
    try:
        r = subprocess.run(["claude", "-p", prompt, "--model", "haiku"],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "(judge timed out)"
    text = (r.stdout or "").strip()
    return text.upper().startswith("PASS"), (text.splitlines()[0] if text else "(no judge output)")


def grade(case, output, use_judge):
    fails = []
    for s in case.get("must_contain", []):
        if s not in output:
            fails.append(f"missing required text: {s!r}")
    anyof = case.get("must_contain_any")           # at least one — robust to synonyms/phrasing
    if anyof and not any(s in output for s in anyof):
        fails.append(f"none of the accepted phrasings present: {anyof}")
    for s in case.get("must_not_contain", []):
        if s in output:
            fails.append(f"contains forbidden text: {s!r}")
    rx = case.get("must_not_match")
    if rx and re.search(rx, output):
        fails.append(f"matched forbidden pattern: {rx}")
    note = ""
    if use_judge and case.get("judge_rubric"):
        ok, why = _judge(case["judge_rubric"], output)
        note = f"  · judge: {why}"
        if not ok:
            fails.append(f"judge FAIL: {why}")
    return fails, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="*", help="name glob filter")
    ap.add_argument("--judge", action="store_true", help="also run the haiku LLM-judge")
    args = ap.parse_args()

    all_cases = yaml.safe_load(CASES.read_text()) or []
    cases = [c for c in all_cases if fnmatch.fnmatch(c["name"], args.case)]
    if not cases:
        print(f"no cases match {args.case!r}", file=sys.stderr)
        return 2

    tmp = tempfile.mkdtemp(prefix="drift-eval-")
    _STRING_GRADERS = ("must_contain", "must_contain_any", "must_not_contain", "must_not_match")
    passed = failed = skipped = 0
    for c in cases:
        # A semantic case is judge-only; without --judge it has NO active grader — SKIP it loudly
        # rather than silently "pass" an ungraded run (a green with no check is worse than a skip).
        has_string = any(c.get(k) for k in _STRING_GRADERS)
        has_judge = bool(c.get("judge_rubric")) and args.judge
        if not (has_string or has_judge):
            print(f"[SKIP] {c['name']} — no active grader (needs --judge, or add a string rule)")
            skipped += 1
            continue
        env = dict(os.environ, EVAL_TMP=tmp)
        if c.get("setup"):
            subprocess.run(["bash", "-c", c["setup"]], env=env, capture_output=True, text=True)
        out = _run_claude(c["prompt"].replace("$EVAL_TMP", tmp), c.get("plugin", False),
                          c.get("timeout", 180))
        fails, note = grade(c, out, args.judge)
        print(f"[{'PASS' if not fails else 'FAIL'}] {c['name']}{note}")
        for f in fails:
            print(f"        - {f}")
        passed += not fails
        failed += bool(fails)
    print(f"\n{passed}/{passed + failed} passed" + (f" ({skipped} skipped)" if skipped else ""))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

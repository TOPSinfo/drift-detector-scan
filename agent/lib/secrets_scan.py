"""Run the gitleaks secret-detection engine (injected for tests) and normalize its JSON report.

gitleaks scans a repo's git history (not just the working tree) for regex/entropy matches
against known credential shapes. It is a separate, deliberately-simpler binary from ast-grep:
no rule metadata to echo, no vendor/techKey classification — a secret is a secret regardless
of which vendor's API it belongs to.

The matched secret VALUE is never carried past this module. gitleaks' own report includes it
(`Secret`/`Match` fields) so a human re-reading raw gitleaks output can act on it directly, but
our own drift.json/GitLab issues must say only WHERE a secret is (repo, file, line, commit),
never repeat the live value into a second document.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys


def _resolve_gitleaks() -> str:
    """Locate the gitleaks binary. Mirrors agent.lib.scan_util.resolve_engine's PATH-then-
    venv-bin lookup for ast-grep: bin/drift-scan downloads gitleaks into the venv's bin/,
    next to the venv's own python, and a bare `subprocess.run(["gitleaks", ...])` relying
    on PATH alone would never find it there.

    Unlike resolve_engine, this never raises: gitleaks is OPTIONAL — a repo's secrets
    scan degrading to UNKNOWN is fine, a whole scan refusing to run is not. When gitleaks
    can't be found anywhere, the bare name is returned so the resulting
    FileNotFoundError still flows through run_secrets_scan's own fault isolation below.
    """
    p = shutil.which("gitleaks")
    if p:
        return p
    cand = os.path.join(os.path.dirname(sys.executable), "gitleaks")
    return cand if os.path.exists(cand) else "gitleaks"


def _default_run(args: list) -> str:
    """Spawn gitleaks and return its stdout — the `run` seam's contract, unchanged.

    A NON-ZERO exit is raised, not returned. We pass `--exit-code 0` precisely so that
    *finding secrets* exits 0 (gitleaks' native default is 1-when-found), which leaves
    non-zero meaning one thing only: the tool itself failed. gitleaks on a directory it
    cannot read — a plain code folder with no `.git`, which this scanner explicitly
    supports — exits non-zero with EMPTY stdout, and returning that bare stdout made a
    failed scan indistinguishable from a clean one. "Cannot see" is not "clean".
    """
    proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args,
                                            output=proc.stdout, stderr=proc.stderr)
    return proc.stdout


def _failure_message(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        tail = (exc.stderr or exc.output or "").strip().splitlines()
        detail = tail[-1] if tail else "no output"
        return (f"gitleaks exited {exc.returncode} ({detail}); treating the scan as "
                "FAILED, not empty")
    if isinstance(exc, subprocess.TimeoutExpired):
        return (f"gitleaks timed out after {exc.timeout}s; treating the scan as "
                "FAILED, not empty")
    return f"gitleaks could not be run ({exc}); treating the scan as FAILED, not empty"


def run_secrets_scan(repo_path: str, *, run=_default_run) -> dict:
    errors = []
    try:
        out = run([_resolve_gitleaks(), "detect", "--source", repo_path, "--report-format",
                   "json", "--report-path", "/dev/stdout", "--exit-code", "0", "--no-banner"])
    except (OSError, subprocess.SubprocessError) as exc:
        # FAULT ISOLATION. A missing binary (FileNotFoundError), an unrunnable one, a
        # timeout or a non-zero exit is a failure of THIS signal — it must not propagate,
        # because the caller's per-repo try/except would then discard that repo's
        # already-computed ast-grep endpoints, manifests and CVEs and file the whole repo
        # under reposErrored for a reason that has nothing to do with them. Degrade the
        # way the malformed-JSON branch below already does: no matches, and an error that
        # says so out loud.
        return {"matches": [],
                "errors": [{"message": _failure_message(exc), "path": repo_path}]}
    try:
        data = json.loads(out) if out and out.strip() else []
    except ValueError as exc:
        # Same discipline as engine.py's run_scan: a crash or warning line ahead of the JSON
        # must not read as "scanned cleanly, found nothing".
        data = []
        errors.append({"message": f"gitleaks output was not valid JSON ({exc}); "
                                  "treating the scan as FAILED, not empty",
                       "path": repo_path})
    matches = [{
        "ruleId": m.get("RuleID", ""),
        "path": m.get("File", ""),
        "line": m.get("StartLine", -1),
        "commit": m.get("Commit", ""),
        "fingerprint": m.get("Fingerprint", ""),
        # deliberately no "secret"/"match" key — see module docstring
    } for m in data]
    return {"matches": matches, "errors": errors}

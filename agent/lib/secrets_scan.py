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
import subprocess


def _default_run(args: list) -> str:  # pragma: no cover - spawns the real binary
    proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return proc.stdout


def run_secrets_scan(repo_path: str, *, run=_default_run) -> dict:
    out = run(["gitleaks", "detect", "--source", repo_path, "--report-format", "json",
               "--report-path", "/dev/stdout", "--exit-code", "0", "--no-banner"])
    errors = []
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

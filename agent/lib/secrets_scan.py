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
import tempfile


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

    VERIFIED AGAINST A REAL BINARY, in this project's own container image: gitleaks
    shells out to the real `git`, which refuses a repo it doesn't own — "detected
    dubious ownership" — whenever the scanned tree's UID differs from the running
    process's, exactly the case of a CI runner mounting a host-owned checkout into a
    container. That failure does NOT raise: git logs an ERR line, gitleaks reports "0
    commits scanned" and "no leaks found", and exits 0 — a silent false clean, worse
    than the /dev/stdout bug below because it produces a validly-empty report. Setting
    `safe.directory=*` via git's own GIT_CONFIG_* env-var mechanism (git >=2.31, no
    global config file touched, scoped to this one subprocess) fixes it; every ast-grep-
    engine-adjacent `git` invocation elsewhere in this codebase (agent.lib.scan_util's
    git_meta, notably) has the SAME exposure and is NOT fixed by this — flagged
    separately, out of this module's scope.
    """
    env = {**os.environ, "GIT_CONFIG_COUNT": "1",
           "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": "*"}
    # mkstemp, not NamedTemporaryFile: VERIFIED AGAINST A REAL BINARY, in this project's
    # own container image (overlayfs) — reading gitleaks' report back through the SAME
    # file object this process had open returned empty even though gitleaks logged
    # "leaks found" and exited 0; re-opening the identical path fresh saw the real
    # content. gitleaks replaces the file rather than writing into the inode we already
    # had open. mkstemp only reserves the NAME (the fd is closed immediately below); the
    # actual read happens through a brand-new open(), which is what worked.
    fd, report_path = tempfile.mkstemp(prefix="drift-gitleaks-", suffix=".json")
    os.close(fd)
    try:
        # VERIFIED AGAINST A REAL BINARY, in this project's own container image:
        # `--report-path /dev/stdout` silently produced ZERO bytes even on a scan that
        # found a real leak — no error, no log line about it, exit 0. A real temp file
        # is gitleaks' own documented, portable report mechanism; /dev/stdout is not.
        full_args = [*args, "--report-path", report_path]
        proc = subprocess.run(full_args, capture_output=True, text=True, timeout=300,
                              env=env)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, full_args,
                                                output=proc.stdout, stderr=proc.stderr)
        with open(report_path, encoding="utf-8") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(report_path)
        except OSError:
            pass


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
    args = [_resolve_gitleaks(), "detect", "--source", repo_path, "--report-format", "json",
            "--exit-code", "0", "--no-banner"]
    if not os.path.exists(os.path.join(repo_path, ".git")):
        # VERIFIED AGAINST A REAL GITLEAKS 8.30.1 BINARY: `detect` on a directory with no
        # `.git`, without this flag, silently returns `[]` at exit 0 — no warning, no
        # error. This scanner explicitly supports a plain code folder with no `.git` (see
        # test_zero_repos_is_not_clean.py's PM-reported ingestion feature); without
        # --no-git that entire use case got zero secret-scanning signal and looked
        # clean while doing it. Never add this for a real repo — it silently drops
        # gitleaks' git-HISTORY scan, the module's whole reason to exist over a plain grep.
        args.append("--no-git")
    try:
        out = run(args)
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
        "path": _relativize(m.get("File", ""), repo_path),
        "line": m.get("StartLine", -1),
        "commit": m.get("Commit", ""),
        "fingerprint": _relativize(m.get("Fingerprint", ""), repo_path),
        # deliberately no "secret"/"match" key — see module docstring
    } for m in data]
    return {"matches": matches, "errors": errors}


def _relativize(value: str, repo_path: str) -> str:
    """VERIFIED AGAINST A REAL BINARY: in --no-git mode (a plain folder with no .git),
    gitleaks reports `File`/`Fingerprint` relative to whatever `--source` was given — and
    repo_scan.py always passes an ABSOLUTE repo_abs, so that means an absolute path
    leaking local filesystem structure into inventory.json/drift.json/GitLab issues. Git
    mode always reports repo-relative paths regardless of --source, so this only ever
    fires for the --no-git branch; a value that isn't an absolute path under repo_path is
    left untouched (e.g. Fingerprint's non-path segments, or a value from an older
    cached record shape)."""
    if value.startswith(repo_path.rstrip(os.sep) + os.sep):
        return os.path.relpath(value, repo_path)
    return value

"""Git metadata + engine resolution for the inventory scanner. Git is injected for tests."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys


def _default_git(args: list) -> str:  # pragma: no cover - real git subprocess
    proc = subprocess.run(["git"] + args, capture_output=True, text=True, timeout=30)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def normalize_remote(raw) -> str | None:
    """Normalize a git remote to a clean `https://host/owner/repo`, or None.

    STRIPS any embedded credentials (`https://user:token@host/…`) — the credential-leak guard:
    a token must never reach the shared dashboard. Returns None for anything it can't parse to a
    clean scheme://host/path (fail safe → no link rather than a risky one).
    """
    s = str(raw or "").strip()
    if not s:
        return None
    if "://" not in s:                                   # scp-style ssh: git@host:owner/repo(.git)
        m = re.match(r"^[\w.+-]+@([\w.-]+):(.+)$", s)
        if not m:
            return None
        host, path = m.group(1), m.group(2)
    else:                                                # scheme://[userinfo@]host[:port]/path
        m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([\w.-]+)(?::\d+)?/(.+)$", s, re.I)
        if not m:
            return None
        host, path = m.group(1), m.group(2)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host or not path or "@" in host or "@" in path:
        return None
    return f"https://{host}/{path}"


def git_meta(repo_abs: str, *, run=_default_git) -> dict:
    def g(*a):
        return run(["-C", repo_abs, *a]) or ""
    return {
        "head_sha": g("rev-parse", "HEAD"),
        "remote_url": normalize_remote(g("remote", "get-url", "origin")),
        "ref": g("rev-parse", "--abbrev-ref", "HEAD"),
        "last_activity_at": g("log", "-1", "--format=%cI"),
        "ref_is_default": True,          # best-effort locally (v1 simplification)
    }


def repo_scope_id(repo_abs: str, meta: dict | None = None, *, git=_default_git) -> str:
    """The identity a repo-SCOPED idiom (path-constant, sdk-profile) is matched against.

    It MUST be the git remote identity (`endpoints._repo_in_scope` keys on the remote's
    host/path suffix), falling back to the local path only when there is no remote. The scan
    pipeline (`repo_scan`) and the absorb gate (`cli._cmd_absorb`) must derive it the SAME way —
    a gate that passed the raw local checkout path instead saw `_repo_in_scope` return False for
    a clone whose folder name differs from `org/repo` (`double-break_spapi-php` vs
    `spapi-php`), so the idiom silently never applied and `attributedAfter == attributedBefore`.
    Pass `meta` when git_meta was already computed to avoid a second subprocess."""
    m = meta if meta is not None else git_meta(repo_abs, run=git)
    return m.get("remote_url") or repo_abs


def resolve_engine(engine: str = "ast-grep") -> str:
    """Locate the ast-grep binary (static, no runtime). bin/drift-scan fetches it
    into the venv on first run; $DRIFT_ENGINE or PATH also work."""
    for name in (engine, "ast-grep"):
        p = shutil.which(name)
        if p:
            return p
        cand = os.path.join(os.path.dirname(sys.executable), name)
        if os.path.exists(cand):
            return cand
    raise RuntimeError("ast-grep not found — install it (https://ast-grep.github.io) "
                       "or re-run bin/drift-scan, which fetches it automatically.")


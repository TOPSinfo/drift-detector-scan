"""Git metadata + engine resolution for the inventory scanner. Git is injected for tests."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys


def safe_git_env() -> dict:
    """Env vars for any `git` subprocess this tool spawns, so it can read a repo's
    history regardless of the UID that owns it on disk.

    VERIFIED AGAINST A REAL BINARY, in this project's own container image: git refuses a
    repo it doesn't own ("detected dubious ownership") whenever the scanned tree's UID
    differs from the running process's — exactly a CI runner mounting a host-owned
    checkout into a container. `_default_git` below then silently returns "" on ANY git
    failure, indistinguishable from a legitimately-empty result (e.g. a fresh repo with
    no commits yet) — reproduced directly: `git rev-parse HEAD` inside the built image,
    against a host-owned mount, failed with this exact error and no caller surfaced it.
    GIT_CONFIG_* is git's own per-invocation config mechanism (git >=2.31) — no global
    config file is written, and the setting is scoped to whichever subprocess this env
    dict is passed to. Every git-shelling-out call site in this codebase uses this.
    """
    return {**os.environ, "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": "*"}


def _default_git(args: list) -> str:  # pragma: no cover - real git subprocess
    proc = subprocess.run(["git"] + args, capture_output=True, text=True, timeout=30,
                          env=safe_git_env())
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


def git_meta(repo_abs: str, *, run=_default_git,
             configured_branch: str | None = None) -> dict:
    def g(*a):
        return run(["-C", repo_abs, *a]) or ""
    return {
        "head_sha": g("rev-parse", "HEAD"),
        "remote_url": normalize_remote(g("remote", "get-url", "origin")),
        "ref": g("rev-parse", "--abbrev-ref", "HEAD"),
        "last_activity_at": g("log", "-1", "--format=%cI"),
        # False exactly when the deployment NAMED a branch. Previously hardcoded True
        # ("best-effort locally, v1 simplification"); once a branch can be configured
        # that constant is a false statement in a published artifact, and it is the only
        # thing that makes an override falsifiable from the report rather than from the
        # config file. The checked-out ref alone cannot answer this: it cannot tell you
        # whether someone asked for that branch or the remote merely defaulted to it.
        "ref_is_default": configured_branch is None,
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


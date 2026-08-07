"""Pin-verifying clone of the corpus into <sandbox>/<category>/<name>. Git is injected
(git(args, cwd=None) -> stdout on success; RAISES on non-zero exit — callers must not
return "" to signal failure, since "" is also the legitimate result of a clean
`git status --porcelain`). Reproducibility is enforced: after checkout, HEAD must
equal the declared sha (hard-fail on mismatch = corpus drift), and a dirty tree is refused.
Clones are third-party public code and are never committed."""
from __future__ import annotations

import os


def _default_git(args, cwd=None) -> str:  # pragma: no cover - real git subprocess
    import subprocess
    cmd = ["git"] + (["-C", cwd] if cwd else []) + args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def _dest(sandbox_root, entry) -> str:
    name = os.path.basename(entry["repo"].rstrip("/"))
    return os.path.join(sandbox_root, entry["category"], name)


def sync_corpus(entries: list, sandbox_root: str, *, git=_default_git, no_fetch=False) -> list:
    paths = []
    for e in entries:
        dest = _dest(sandbox_root, e)
        sha = e["sha"]
        if os.path.isdir(os.path.join(dest, ".git")):
            if not no_fetch:
                git(["fetch", "origin", sha], cwd=dest)
            dirty = git(["status", "--porcelain"], cwd=dest)
            if dirty:
                raise RuntimeError(f"{dest}: dirty/uncommitted tree — refusing to checkout over it")
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            git(["clone", "--filter=blob:none", e["url"], dest])
        git(["checkout", sha], cwd=dest)
        head = git(["rev-parse", "HEAD"], cwd=dest)
        if head != sha:
            raise RuntimeError(f"{dest}: SHA mismatch — HEAD {head!r} != pinned {sha!r} (corpus drift)")
        paths.append(dest)
    return paths

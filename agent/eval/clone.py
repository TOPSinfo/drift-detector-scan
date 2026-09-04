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
    from agent.lib.scan_util import safe_git_env
    # VERIFIED AGAINST A REAL BINARY, in this project's own container image: git refuses
    # a repo it doesn't own ("detected dubious ownership") whenever the checked-out
    # tree's UID differs from the running process's — e.g. a sandbox_root mounted from
    # the host into a container running the eval. This module already fails LOUD on any
    # git error (unlike agent.lib.scan_util's silent ""), so the exposure here is an
    # unnecessary hard failure rather than a silent false clean — still worth closing.
    cmd = ["git"] + (["-C", cwd] if cwd else []) + args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          env=safe_git_env())
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def checkout_name(repo: str) -> str:
    """The on-disk checkout name for a corpus repo: `<org>__<repo>`.

    THE ONE definition. `agent/eval/score.py` joins scan results back to corpus entries by
    this name, and when the two derived it independently the eval broke silently: _dest was
    changed to include the org (to fix a real collision) while score still keyed on
    `basename(repo)`, so every repo scanned fine and then scored as `errored`, and the gate
    reported nine undetected repos that were actually detected. Import it; never re-derive it.
    """
    return str(repo).rstrip("/").replace("/", "__")


def _dest(sandbox_root, entry) -> str:
    """`<sandbox>/<category>/<org>__<repo>`.

    The org is part of the path on purpose. Keying on `basename(repo)` alone collided:
    `amzn/selling-partner-api-sdk` and `amzapi/selling-partner-api-sdk` are both real, both
    in category `sp`, and both landed on one directory — so the second entry ran
    `git fetch origin <its sha>` inside the FIRST one's checkout and died with
    `upload-pack: not our ref`, taking `drift-eval run sp` down with it. Two different repos
    must never share a checkout, however similarly they are named.
    """
    name = checkout_name(entry["repo"])
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

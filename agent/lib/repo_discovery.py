"""Multi-root, recursive git-repo discovery for the Drift Detector inventory scanner.

Pure filesystem discovery (pathlib only, no git subprocess): a directory "is a repo"
iff it contains a `.git` entry. Discovery does not descend into a found repo (its
submodules/vendored `.git` dirs are not separate repos to scan) nor into common
noise directories (`_SKIP_DIRS`).

Repo *identity* (the diff/tracking key) is derived deterministically and
independently of the order of `roots`:
- each repo's "home root" is the nearest ancestor root (longest path prefix);
- the base identity is the repo's path relative to that home root (or the home
  root's basename when the repo *is* the root);
- a repo whose *resolved* path escapes every root (an in-tree symlink pointing
  outside all roots) has no ancestor root — it falls back to its in-tree walk
  path relative to the root it was discovered under;
- if two *different* repos would collide on the same identity (e.g. two roots
  that share a basename), each is disambiguated by prefixing with its root's
  path relative to the common ancestor of all roots — unique by construction,
  since distinct absolute paths stay distinct relative to a shared prefix.
"""
from __future__ import annotations

import os
from pathlib import Path

_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "dist", "build", "target", "__pycache__"}


def _find_git_repos(root: Path, visited: set | None = None):
    """Yield each dir under (and including) root that is a git repo, recursively.

    A repo is a dir containing a `.git` entry. Once found, its subtree is not
    descended into. Dirs named in `_SKIP_DIRS` are never descended into.
    Symlinks are followed, but a `visited` set of resolved paths guards against
    symlink cycles causing unbounded recursion. Yields the *walk* path (which
    may contain symlink components), so callers can relate it to `root`.
    """
    if visited is None:
        visited = set()
    resolved = root.resolve()
    if resolved in visited:
        return
    visited.add(resolved)

    if (root / ".git").exists():
        yield root
        return
    try:
        children = sorted(d for d in root.iterdir() if d.is_dir())
    except OSError:
        return
    for child in children:
        if child.name in _SKIP_DIRS:
            continue
        yield from _find_git_repos(child, visited)


def diagnose_root(root) -> str | None:
    """Why did this root yield no scannable repo? None if it looks fine.

    A scan that discovers nothing must be able to SAY why, because the alternative —
    reporting a clean bill over a folder it never read — is the exact failure this tool
    exists to refuse. "0 findings" and "0 repos" are opposite outcomes that looked
    identical: a green checkmark.
    """
    s = str(root)
    if "://" in s or s.startswith("git@"):
        return (f"{s!r} looks like a URL — this version scans LOCAL paths only. "
                f"Clone it first, then point at the checkout.")
    p = Path(s)
    if not p.exists():
        return f"{s!r} does not exist — check the path."
    if p.is_file():
        return f"{s!r} is a file, not a directory."
    # a real directory that simply has no git repo under it
    if not any(True for _ in _find_git_repos(p)):
        has_code = any(p.rglob("*.php")) or any(p.rglob("*.js")) or any(p.rglob("*.py"))
        if has_code:
            return (f"{s!r} has source files but no .git — this version only scans git "
                    f"working trees. `git init` it, or clone the repo, then re-run.")
        return f"{s!r} contains no git repository."
    return None


def discover_repos(roots: list) -> list:
    """Find all git repos recursively beneath each of `roots`.

    Returns a sorted list of (abs_repo_path, identity) tuples, deduped by
    resolved absolute repo path. Identity is order-independent and
    collision-free — see the module docstring for the scheme.
    """
    resolved_roots = [Path(r).resolve() for r in roots]

    # Map each distinct repo (by resolved abs path) to the root/walk-path it was
    # discovered under. Iterate roots in a deterministic order so the fallback
    # identity for symlink-escaped repos does not depend on the input order.
    found: dict = {}
    for root in sorted(resolved_roots, key=lambda p: (len(p.parts), str(p))):
        for repo in _find_git_repos(root):
            found.setdefault(repo.resolve(), (root, repo))

    def _home_root(repo: Path):
        # Nearest ancestor root (longest path); deterministic, order-independent.
        # None when the repo's resolved path escapes every root (symlink target).
        candidates = [r for r in resolved_roots if r == repo or r in repo.parents]
        return max(candidates, key=lambda r: (len(r.parts), str(r))) if candidates else None

    common = None
    if len(resolved_roots) > 1:
        try:
            common = Path(os.path.commonpath([str(r) for r in resolved_roots]))
        except ValueError:  # no common path (e.g. different drives)
            common = None

    def _rel_to_common(p: Path) -> str:
        if common is not None:
            return p.relative_to(common).as_posix()
        return p.relative_to(p.anchor).as_posix()  # full path minus anchor -> still unique

    # base: repo -> (root_used_for_disambiguation, base_identity, is_root_itself)
    base: dict = {}
    for repo in found:
        hr = _home_root(repo)
        if hr is not None:
            identity = hr.name if repo == hr else repo.relative_to(hr).as_posix()
            base[repo] = (hr, identity, repo == hr)
        else:
            disc_root, walk = found[repo]
            identity = walk.relative_to(disc_root).as_posix() or disc_root.name
            base[repo] = (disc_root, identity, False)

    # Collisions only occur across different roots -> disambiguate uniquely.
    owners: dict = {}
    for repo, (_root, identity, _self) in base.items():
        owners.setdefault(identity, []).append(repo)

    result = []
    for repo, (dis_root, identity, is_root_itself) in base.items():
        if len(owners[identity]) > 1:
            if is_root_itself:            # base identity was just the basename
                identity = _rel_to_common(dis_root)
            else:
                identity = f"{_rel_to_common(dis_root)}/{identity}"
        result.append((str(repo), identity))

    return sorted(result)

"""Turn whatever the user points at — a checkout, a plain folder, or a URL — into
scannable project directories.

The scanner used to hard-require a `.git` directory, so a URL, a typo, or a client's
zipped source folder all resolved to nothing and the run reported a clean bill. A
consultancy scanning client code gets all three shapes, so the input contract is:

    a git checkout   scanned as today — HEAD sha for caching, remote for permalinks
    a plain folder   scanned as ONE project — no sha, no permalinks, said so plainly
    a git/GitLab URL cloned into <state>/sources/, then scanned as a checkout
    one or many      any mix of the above

Auth for private URLs reuses the MACHINE's existing git setup (credential helper, SSH
keys) — if `git clone <url>` works in your terminal, it works here. A GITLAB_TOKEN in the
environment is honoured at clone time via a transient credential that is never written to
.git/config or to the tool's state.

A source that resolves to nothing is an ERROR carried back to the caller, never a silent
drop — "couldn't read it" and "read it, all clean" must stay distinguishable.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from agent.lib.repo_discovery import discover_repos, diagnose_root
from agent.lib import gitlab, scope_edges

_URL_RE = re.compile(r"^(https?://|git@|ssh://|git://|file://)")
_CODE_GLOBS = ("*.php", "*.js", "*.ts", "*.py", "*.rb", "*.go", "*.java", "*.cs")


def is_url(s) -> bool:
    return bool(_URL_RE.match(str(s)))


def slug(url) -> str:
    """A stable, filesystem-safe directory name for a cloned URL. The sha suffix keeps
    two different URLs that share a basename (owner-a/api, owner-b/api) from colliding."""
    s = _URL_RE.sub("", str(url)).replace(":", "/")
    if s.endswith(".git"):
        s = s[:-4]
    parts = [p for p in re.split(r"/+", s) if p]
    base = "-".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "repo")
    base = re.sub(r"[^A-Za-z0-9._-]", "-", base)
    return f"{base}-{hashlib.sha256(str(url).encode()).hexdigest()[:8]}"


def _has_code(path: str) -> bool:
    p = Path(path)
    return any(next(p.rglob(g), None) is not None for g in _CODE_GLOBS)


def _default_clone(url: str, dest: str, *, branch: str | None = None) -> tuple[bool, str]:
    """Clone (or update) `url` into `dest` using the machine's own git auth.

    A GITLAB_TOKEN / DRIFT_GIT_TOKEN in the environment is used via a transient in-memory
    credential helper so it authenticates the clone without ever landing in .git/config
    (the stored remote stays tokenless) or in the tool's state.

    `branch` names the ref to scan. Absent, git picks the remote's default HEAD — today's
    behaviour, unchanged.
    """
    dest_p = Path(dest)
    env = os.environ.copy()
    tok = env.get("GITLAB_TOKEN") or env.get("DRIFT_GIT_TOKEN")
    cred = []
    if tok and str(url).startswith("http"):
        env["DRIFT_CLONE_TOKEN"] = tok
        cred = ["-c", "credential.helper=!f(){ echo username=oauth2; "
                      'echo "password=$DRIFT_CLONE_TOKEN"; }; f']
    try:
        if (dest_p / ".git").exists():
            # The refspec is load-bearing. A bare `fetch origin` resolves FETCH_HEAD to the
            # remote's DEFAULT branch, so an already-cloned repo would ignore its configured
            # branch on every run after the first — and nothing in the artifacts would show it,
            # because the scan would look like a perfectly ordinary successful scan.
            fetch = ["git", *cred, "-C", dest, "fetch", "--depth", "1", "origin"]
            if branch:
                fetch.append(branch)
            r = subprocess.run(fetch, capture_output=True, text=True, timeout=300, env=env)
            if r.returncode != 0:
                if branch:
                    # Do NOT keep the existing clone: it sits on some other branch, and scanning
                    # it would report the wrong code under the right repo's name.
                    return False, (f"branch {branch!r} could not be fetched: "
                                   f"{r.stderr.strip()[:120]}")
                return True, f"kept existing clone (fetch failed: {r.stderr.strip()[:120]})"
            subprocess.run(["git", "-C", dest, "reset", "--hard", "FETCH_HEAD"],
                           capture_output=True, text=True, timeout=60, env=env)
            return True, "updated"
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", *cred, "clone", "--depth", "1"]
        if branch:
            # --single-branch: without it a shallow clone still writes remote-tracking refs for
            # every other branch, which is transfer paid for nothing on a fleet this size.
            cmd += ["--branch", branch, "--single-branch"]
        cmd += [str(url), dest]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        if r.returncode != 0 and branch:
            return False, (f"branch {branch!r} not found on the remote: "
                           f"{(r.stderr or r.stdout).strip()[:160]}")
        return r.returncode == 0, (r.stderr or r.stdout).strip()[:200]
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)[:200]


def resolve_sources(roots: list, state_dir: str, *, clone=None, expand_group=None) -> dict:
    """Resolve every root to scannable projects. Returns:

        {"projects": [(abs_dir, identity, kind)],
         "branches": {abs_dir: branch},          # only for roots that NAMED one
         "errors": [{"root", "reason"}]}

    kind ∈ {remote, local-git, local-plain} — carried into the report so a reader knows a
    plain-folder result has no history behind it, rather than assuming a full scan.

    `clone` and `expand_group` are injected so this is testable without network.
    """
    clone = clone or _default_clone
    expand_group = expand_group if expand_group is not None else gitlab.expand_group
    sources_root = Path(state_dir) / "sources"
    projects: list = []
    errors: list = []
    # abs_dir -> the branch the config ASKED for. Kept beside `projects` rather than widened into
    # its tuples: that shape is documented as (abs_dir, identity, kind) and unpacked positionally
    # in inventory_scan and in existing tests, so widening it would break every one of them
    # silently. Absent for a root that named no branch, which is how git_meta tells "asked for
    # this ref" apart from "the remote happened to default to it".
    branches: dict = {}
    # identity -> the branch it was cloned on (None = the remote's default). A dict,
    # not a set, so a later entry naming a DIFFERENT branch can be caught rather than
    # silently dropped by the dedupe.
    cloned_ids: dict = {}

    def _clone_url(url: str, branch: str | None = None) -> None:
        """Clone one repo URL into <state>/sources and add its projects (or an error)."""
        # Dedupe by canonical git identity BEFORE cloning: a fleet may list a group AND a
        # member of it, so the same repo arrives twice — once expanded as `…/repo.git`, once
        # explicit as `…/repo`. Those slug to different dirs, so the abs-dir dedupe below can't
        # catch them; without this they scan twice and drift.md renders duplicate rows.
        iden = scope_edges.identity(url)
        if iden:
            if iden in cloned_ids:
                # Already cloned via another entry — usually a fleet listing a group AND one of
                # its members, which is fine and stays silent. But if THIS entry names a branch
                # the earlier one did not, first-wins would discard it and scan the default
                # branch with nothing to show for it: the config asked for `dev`, the report says
                # nothing, and the repo reads as scanned. That is the silent-wrong-branch failure
                # the branch feature exists to remove, arriving through the config's line order.
                # The config says two different things about one repository; refuse rather than
                # pick, exactly as a branch on a group URL is refused.
                if branch and cloned_ids[iden] != branch:
                    errors.append({"root": url, "reason": (
                        f"{url!r} was already resolved by an earlier fleet entry"
                        + (f" on branch {cloned_ids[iden]!r}" if cloned_ids[iden]
                           else " on its default branch")
                        + f", so `branch: {branch}` here would be silently ignored. Give the "
                          f"repository ONE entry, or list it before the group that also covers "
                          f"it.")})
                return
            cloned_ids[iden] = branch
        dest = sources_root / slug(url)
        ok, msg = clone(url, str(dest), branch=branch)
        if not ok:
            errors.append({"root": url, "reason": f"could not clone {url!r}: {msg} — this "
                           "reuses your machine's git auth; can you `git clone` it in a "
                           "terminal?"})
            return
        _add_local(str(dest), url, from_url=True, branch=branch)

    def _add_local(local: str, label: str, *, from_url: bool,
                   branch: str | None = None) -> None:
        repos = discover_repos([local])          # git checkouts under the resolved dir
        if repos:
            kind = "remote" if from_url else "local-git"
            for abs_, identity in repos:
                projects.append((abs_, identity, kind))
                if branch:
                    branches[abs_] = branch
        elif _has_code(local):
            ident = slug(label) if from_url else Path(local).resolve().name
            abs_ = str(Path(local).resolve())
            projects.append((abs_, ident, "remote" if from_url else "local-plain"))
            if branch:
                branches[abs_] = branch
        else:
            errors.append({"root": label, "reason": (diagnose_root(local)
                           or f"{label!r} resolved to a folder with no scannable code")})

    for root in roots:
        # roots are (url_or_path, branch|None) since the config gained a branch. A bare string is
        # still accepted — several callers and every existing test pass one — and means "no
        # branch configured", which is exactly what it meant before.
        if isinstance(root, (tuple, list)):
            raw_root = root[0]
            branch = root[1] if len(root) > 1 else None
        else:
            raw_root, branch = root, None
        s = str(raw_root)
        if is_url(s):
            # A GitLab GROUP url expands to its member repos; a project url (or non-GitLab
            # host) comes back None and is cloned directly.
            group = expand_group(s) if gitlab.is_group_url(s) else None
            if group is not None:
                # A namespace is only knowable HERE — expand_group returning a list IS the test,
                # which is why this cannot live in load(). One branch name cannot be assumed to
                # mean the same thing across every repo under a group, and a per-repo fallback
                # would produce a scan mixing branches with nothing in the report to say which.
                if branch:
                    errors.append({"root": s, "reason": (
                        f"{s!r} expands to a group of {len(group)} project(s), so `branch: "
                        f"{branch}` cannot be applied — one branch name is not guaranteed to mean "
                        f"the same thing in every repo under it. List the repos individually "
                        f"with their own branches.")})
                    continue
                active = [p for p in group if not p["archived"]]
                if not active:
                    skipped = f" ({len(group)} archived, skipped)" if group else ""
                    errors.append({"root": s, "reason": f"GitLab group {s!r} has no active "
                                   f"projects to scan{skipped}."})
                    continue
                for proj in active:
                    _clone_url(proj["url"])
            else:
                _clone_url(s, branch)
        else:
            p = Path(s)
            if not p.exists() or p.is_file():
                errors.append({"root": s, "reason": diagnose_root(s)})
                continue
            _add_local(s, s, from_url=False, branch=branch)

    # dedupe by absolute dir, deterministic order
    seen: set = set()
    uniq: list = []
    for abs_, ident, kind in sorted(projects):
        if abs_ in seen:
            continue
        seen.add(abs_)
        uniq.append((abs_, ident, kind))
    return {"projects": uniq, "branches": branches, "errors": errors}

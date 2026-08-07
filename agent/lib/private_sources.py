"""Detect private / unresolvable package sources declared in a repo's manifests.

These are the dependencies whose SOURCE we can't see (so a wrapped integration behind them,
e.g. `tops/ebay-wrapper`, may be under-reported). Surfacing them is how the tool says what it
can't see instead of failing silently.

- npm `package.json`: a dep whose value is a git/file/link/http URL (not a semver range).
- composer `composer.json`: a `repositories` entry pointing at a private VCS (not Packagist;
  local `path` repos are excluded — their source is right there and gets scanned).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent.lib.manifest_scan import _walk

_NPM_PRIVATE = re.compile(r"^(git\+|git:|git@|ssh://|file:|link:|https?://|github:|gitlab:|bitbucket:)", re.I)
# bare GitHub shorthand `user/repo` or `user/repo#ref` (npm treats these as git deps) — but not
# `npm:`/`workspace:` aliases (they contain a colon) and not a semver (no leading digit/^/~/*)
_NPM_SHORTHAND = re.compile(r"^[\w.-]+/[\w.-]+(#.+)?$")
_PRIVATE_REPO_TYPES = {"vcs", "git", "gitlab", "github", "bitbucket"}


def _is_private_npm(spec: str) -> bool:
    s = spec.strip()
    if _NPM_PRIVATE.match(s):
        return True
    return ":" not in s and bool(_NPM_SHORTHAND.match(s))


def _npm_private(content: str) -> list:
    data = json.loads(content)
    out = []
    for section in ("dependencies", "devDependencies"):
        for pkg, spec in (data.get(section) or {}).items():
            if isinstance(spec, str) and _is_private_npm(spec):
                out.append({"pkg": pkg, "via": spec.strip()})
    return out


def _composer_private_repos(content: str) -> list:
    data = json.loads(content)
    repos = data.get("repositories") or []
    items = repos.values() if isinstance(repos, dict) else repos
    urls = []
    for r in items:
        if not isinstance(r, dict):
            continue
        t, url = r.get("type", ""), r.get("url", "")
        if t in _PRIVATE_REPO_TYPES or (t == "composer" and url and "packagist.org" not in url):
            if url:
                urls.append(url)
    return urls


def detect(repo_abs: str) -> dict:
    """{'packages': [{pkg, via}], 'repositories': [private composer repo urls]}."""
    packages, repositories = [], []
    for p in _walk(Path(repo_abs)):
        try:
            if p.name == "package.json":
                packages += _npm_private(p.read_text(encoding="utf-8", errors="ignore"))
            elif p.name == "composer.json":
                repositories += _composer_private_repos(p.read_text(encoding="utf-8", errors="ignore"))
        except (ValueError, OSError):
            continue
    return {"packages": packages, "repositories": sorted(set(repositories))}

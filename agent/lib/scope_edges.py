"""The cross-fleet dependency edge: which private deps a repo pulls in are — or are NOT —
themselves scanned as fleet members.

`private_sources.detect` tells us repo X declares private VCS deps (git URLs we can't crawl
in place). This module answers the follow-on question the scan can't: of those, which are
already first-class repos in THIS fleet (so their calls ARE seen, elsewhere) and which are
referenced-but-absent (a genuine blind spot — the wrapped integration is invisible).

Pure and deterministic: identities in, edges out. No I/O, no network.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

_SCP = re.compile(r"^[\w.+-]+@([\w.-]+):(.+)$")   # git@host:group/repo  (scp-style, no scheme)


def identity(url_or_path: str) -> str:
    """A host+path identity for a git repo, normalized so the same repo written as an https
    URL, an scp remote, or with/without a trailing `.git` compares equal:

        https://git.example.com/grp/repo.git  ─┐
        git@git.example.com:grp/repo.git       ├─▶  git.example.com/grp/repo
        https://GIT.example.com/grp/repo/       ─┘

    Returns '' for something with no host+path to key on (a bare slug, a local path)."""
    s = (url_or_path or "").strip()
    if not s:
        return ""
    m = _SCP.match(s)
    if m:
        host, path = m.group(1), m.group(2)
    elif "://" in s:
        u = urlparse(s)
        host, path = (u.hostname or ""), u.path
    else:
        return ""                                    # not a URL — no reliable identity
    path = re.sub(r"\.git$", "", path.strip("/"))
    host = host.lower()
    if not host or not path:
        return ""
    return f"{host}/{path.lower()}"


def find_missing(consumers: list, fleet_ids: set) -> list:
    """For each consumer `{repo, deps: [url, …]}`, split its private deps into those already
    scanned as fleet members and those referenced-but-absent. `fleet_ids` is the set of
    identities of the repos actually in scope (from the resolved projects).

    Returns one row per consumer that HAS private deps:
        {repo, present: [{url, id}], missing: [{url, id}]}
    A dep whose URL yields no identity is treated as missing (we can't prove it's in fleet).
    Deterministic: rows follow input order; within a row, present/missing sorted by id.
    """
    fleet = {i for i in fleet_ids if i}
    rows = []
    for c in consumers:
        present, missing = [], []
        for url in c.get("deps", []) or []:
            iden = identity(url)
            entry = {"url": url, "id": iden}
            (present if iden and iden in fleet else missing).append(entry)
        if present or missing:
            rows.append({"repo": c.get("repo", ""),
                         "present": sorted(present, key=lambda e: e["id"]),
                         "missing": sorted(missing, key=lambda e: (e["id"], e["url"]))})
    return rows

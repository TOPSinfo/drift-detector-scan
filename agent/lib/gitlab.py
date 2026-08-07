"""Expand a GitLab GROUP url into its member repositories.

A consultancy scans a client's whole fleet, not one repo at a time. Point the tool at a
group (`https://git.example.com/acme`) and this enumerates every project under it (and its
subgroups) via the GitLab API, so the ingestion pipeline clones and scans them all — you
cannot miss a repo the tool discovered for you.

Detection is by the API, not by URL shape (which is ambiguous — `host/acme/web` could be
group `acme` + project `web`, or a nested group). We ask GitLab: is this path a group? If
yes, enumerate; if 404, it is a project (or not GitLab) and the caller falls back to a
single-repo clone. The GitLab token — the same `GITLAB_TOKEN`/`DRIFT_GIT_TOKEN` the clone
auth uses — authorizes the API and is read at call time, never stored.

`fetch` is injected so this is testable without network.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote

_URL = re.compile(r"^(https?://[^/]+)/(.+?)/?$")


def _split(url: str):
    """(api_host, group_path) or (None, None). Strips a trailing .git."""
    m = _URL.match(str(url or ""))
    if not m:
        return None, None
    host, path = m.group(1), m.group(2)
    if path.endswith(".git"):
        path = path[:-4]
    return host, path


def _token() -> str | None:
    return os.environ.get("GITLAB_TOKEN") or os.environ.get("DRIFT_GIT_TOKEN")


def _default_fetch(api_url: str, token: str | None):
    """(status, parsed_json, next_page_str). Raises on network error; a 404 comes back as
    status 404 so `expand_group` can treat 'not a group' as a clean fall-through."""
    headers = {"User-Agent": "drift-detector"}
    if token:
        headers["PRIVATE-TOKEN"] = token
    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:      # noqa: S310
            body = r.read().decode("utf-8", "replace")
            return r.status, json.loads(body) if body else [], r.headers.get("X-Next-Page", "")
    except urllib.error.HTTPError as e:
        return e.code, None, ""


def is_group_url(url: str) -> bool:
    """Cheap shape gate: a bare `https://host` with no path is never a group to expand."""
    host, path = _split(url)
    return bool(host and path)


def expand_group(url: str, *, token: str | None = None, fetch=None) -> list | None:
    """Every project the token can access under the GitLab NAMESPACE at `url` — a group OR
    a user namespace — or None if `url` is a single project (or not enumerable).

    Returns [{url, path, archived}] (url = the clone URL). None means "not a namespace to
    expand" — the path is itself a project, or the API isn't reachable/authorized — and the
    caller should clone `url` directly. An empty list means "a real namespace, but the token
    sees no projects under it".

    Why membership, not the group endpoint: `/groups/:id/projects` 404s for a USER namespace
    (verified: git.example.com/example-org is a user, not a group), and a client's repos live
    under both. `/projects?membership=true` returns exactly what the token can actually
    clone — group-inherited, user-owned, and direct-member — which is the honest set: you
    cannot miss a repo you have access to. We scope it to the namespace by path prefix.
    """
    host, path = _split(url)
    if not host or not path:
        return None
    fetch = fetch or _default_fetch
    token = token or _token()

    # 1. Is the path ITSELF a project? Then it's a single repo, not a namespace to expand.
    try:
        status, _data, _nxt = fetch(f"{host}/api/v4/projects/{quote(path, safe='')}", token)
    except Exception:
        return None
    if status == 200:
        return None

    # 2. Enumerate the token's accessible projects, keep those under this namespace. A
    #    failure mid-enumeration returns None (fall back) rather than a SUBSET — silently
    #    scanning some of a fleet is exactly the miss this feature exists to prevent.
    prefix = path.rstrip("/") + "/"
    out, page = [], 1
    while page:
        api = f"{host}/api/v4/projects?membership=true&per_page=100&page={page}"
        try:
            status, data, nxt = fetch(api, token)
        except Exception:
            return None
        if status != 200 or not isinstance(data, list):
            return None
        for p in data:
            pn = p.get("path_with_namespace", "")
            clone_url = p.get("http_url_to_repo")
            if clone_url and pn.startswith(prefix):
                out.append({"url": clone_url, "path": pn, "archived": bool(p.get("archived"))})
        page = int(nxt) if str(nxt).isdigit() and nxt else 0

    # 3. Empty enumeration is AMBIGUOUS: a genuinely empty namespace, OR a path that 404'd as
    #    a project in step 1 and has no children — e.g. a repo the token can't see, or a typo.
    #    Only a POSITIVE group confirmation justifies reporting "empty group"; otherwise return
    #    None so the caller clones the url directly and surfaces git's real not-found/no-access
    #    error, instead of the misleading "group has no active projects to scan".
    if not out:
        try:
            gstatus, _g, _n = fetch(f"{host}/api/v4/groups/{quote(path, safe='')}", token)
        except Exception:
            return None
        if gstatus != 200:
            return None
    return out

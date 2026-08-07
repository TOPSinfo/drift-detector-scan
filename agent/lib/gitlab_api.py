"""A small GitLab API client for issue + merge-request delivery.

Read AND write (issues, branches, files, MRs), so — unlike agent/lib/gitlab.py, which only
enumerates projects — this supports POST/PUT. `fetch` is injected (same discipline as the
rest of the codebase) so every delivery path is testable without a network or a live GitLab.

`fetch(url, *, method, token, body) -> (status, parsed_json_or_None, next_page_str)`. A 4xx
comes back as its status code (never raised), so callers branch on 404 (absent) vs 200.
The token is read at call time and never stored on disk (the project's hard rule).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import quote


def _default_fetch(url: str, *, method: str = "GET", token: str | None = None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": "drift-detector"}
    if token:
        headers["PRIVATE-TOKEN"] = token
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:      # noqa: S310
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw else None), r.headers.get("X-Next-Page", "")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return e.code, parsed, ""


def _enc(s: str) -> str:
    return quote(str(s), safe="")


class GitLabError(RuntimeError):
    """A GitLab API call returned a non-2xx status we can't proceed past."""


class GitLab:
    def __init__(self, host: str, token: str | None = None, *, fetch=None):
        self.base = f"https://{host}/api/v4"
        self.token = token
        self._fetch = fetch or _default_fetch

    def _call(self, method: str, path: str, *, body=None, params=None):
        url = self.base + path
        if params:
            q = "&".join(f"{k}={_enc(v)}" for k, v in params.items() if v is not None)
            url += ("&" if "?" in url else "?") + q
        return self._fetch(url, method=method, token=self.token, body=body)

    def _paged(self, path: str, *, params=None) -> list:
        out, page = [], 1
        while page:
            p = dict(params or {}, per_page=100, page=page)
            status, data, nxt = self._call("GET", path, params=p)
            if status != 200 or not isinstance(data, list):
                raise GitLabError(f"GET {path} -> {status}")
            out.extend(data)
            page = int(nxt) if str(nxt).isdigit() and nxt else 0
        return out

    # --- reachability ---
    def version(self) -> dict | None:
        """GET /version — the instance version dict, or None if unreachable / token rejected.
        Doubles as the preflight probe: it needs a valid token, so a 401 returns None."""
        status, data, _ = self._call("GET", "/version")
        return data if status == 200 and isinstance(data, dict) else None

    # --- projects ---
    def project(self, path_or_id) -> dict | None:
        """The project dict (id, default_branch, web_url) or None if 404."""
        status, data, _ = self._call("GET", f"/projects/{_enc(path_or_id)}")
        return data if status == 200 else None

    def members(self, project_id) -> list:
        """List a project's members, including inherited (group) members."""
        return self._paged(f"/projects/{_enc(str(project_id))}/members/all")

    def user_id(self, username: str) -> int | None:
        """Resolve a username to a user ID, or None if not found."""
        if not username:
            return None
        status, res, _ = self._call("GET", f"/users?username={_enc(username)}")
        return res[0]["id"] if status == 200 and isinstance(res, list) and res else None

    # --- issues ---
    def list_issues(self, project_id, *, labels: str) -> list:
        return self._paged(f"/projects/{_enc(project_id)}/issues",
                            params={"labels": labels, "state": "all"})

    def create_issue(self, project_id, *, title, description, labels, assignee_ids=None) -> dict:
        body = {"title": title, "description": description, "labels": labels}
        if assignee_ids:
            body["assignee_ids"] = assignee_ids
        status, data, _ = self._call("POST", f"/projects/{_enc(project_id)}/issues", body=body)
        if status not in (200, 201):
            raise GitLabError(f"create issue -> {status}: {data}")
        return data

    def update_issue(self, project_id, iid, **fields) -> dict:
        status, data, _ = self._call("PUT", f"/projects/{_enc(project_id)}/issues/{iid}",
                                     body=fields)
        if status != 200:
            raise GitLabError(f"update issue {iid} -> {status}: {data}")
        return data

    # --- branches + files ---
    def branch(self, project_id, name) -> dict | None:
        status, data, _ = self._call(
            "GET", f"/projects/{_enc(project_id)}/repository/branches/{_enc(name)}")
        return data if status == 200 else None

    def create_branch(self, project_id, name, ref) -> dict:
        status, data, _ = self._call(
            "POST", f"/projects/{_enc(project_id)}/repository/branches",
            params={"branch": name, "ref": ref})
        if status not in (200, 201):
            raise GitLabError(f"create branch {name} -> {status}: {data}")
        return data

    def get_file(self, project_id, path, ref) -> dict | None:
        status, data, _ = self._call(
            "GET", f"/projects/{_enc(project_id)}/repository/files/{_enc(path)}",
            params={"ref": ref})
        return data if status == 200 else None

    def set_file(self, project_id, path, *, branch, content, message, exists: bool) -> dict:
        method = "PUT" if exists else "POST"
        status, data, _ = self._call(
            method, f"/projects/{_enc(project_id)}/repository/files/{_enc(path)}",
            body={"branch": branch, "content": content, "commit_message": message})
        if status not in (200, 201):
            raise GitLabError(f"set file {path} -> {status}: {data}")
        return data

    # --- merge requests ---
    def list_mrs(self, project_id, *, labels: str) -> list:
        return self._paged(f"/projects/{_enc(project_id)}/merge_requests",
                           params={"labels": labels, "state": "all"})

    def create_mr(self, project_id, *, source_branch, target_branch, title,
                  description, labels) -> dict:
        status, data, _ = self._call(
            "POST", f"/projects/{_enc(project_id)}/merge_requests",
            body={"source_branch": source_branch, "target_branch": target_branch,
                  "title": title, "description": description, "labels": labels})
        if status not in (200, 201):
            raise GitLabError(f"create MR -> {status}: {data}")
        return data

    def update_mr(self, project_id, iid, **fields) -> dict:
        status, data, _ = self._call(
            "PUT", f"/projects/{_enc(project_id)}/merge_requests/{iid}", body=fields)
        if status != 200:
            raise GitLabError(f"update MR {iid} -> {status}: {data}")
        return data

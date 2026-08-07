"""Tiny JSON-over-HTTP helper using the standard library (no `requests` dependency).

Injected into the OSV / endoflife clients so tests pass canned callables and never touch
the network. Raises urllib errors on failure, which callers catch to degrade gracefully offline.
"""
from __future__ import annotations

import json
import urllib.request


def default_http(url: str, *, method: str = "GET", body=None, timeout: int = 20) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 (fixed https hosts)
        return json.loads(resp.read().decode())

"""Load the curated vendor-API-sunset catalog and classify a retirement date.

The catalog is the tool's unique layer: OSV/endoflife cover packages/runtimes, this covers
when a *vendor retires an API version* — joined against the endpoint inventory (file:line).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

from agent.lib import catalog_overlay

_DEFAULT = str(Path(__file__).resolve().parent.parent / "vendor_sunsets.yaml")


class MalformedSunset(ValueError):
    """A catalog entry with no usable scope. Raised, never skipped."""


def load_sunsets(path: str | None = None) -> list:
    """Load the catalog. An entry that cannot be scoped is an ERROR, not a skip.

    This silently dropped every entry whose only scope was `path`, so eight sourced
    Amazon SP-API retirements — covering 73 call-sites, 50 of them into APIs that had
    already stopped working — were loaded, discarded, and the audit reported a clean
    Amazon with no indication anything had been thrown away. A catalog that quietly
    forgets what it was taught is worse than an empty one: it looks the same as clean.
    """
    with open(path or _DEFAULT, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    # a default load layers the writable overlay (baseline first); each overlay entry runs
    # the SAME scope validation below, so a malformed absorbed sunset is an error, not a skip
    if path is None:
        raw = list(raw) + catalog_overlay.load_list(catalog_overlay.SUNSETS)
    out = []
    for i, s in enumerate(raw):
        # need a vendor plus a scope: a version (or "*"), a domain, an operation, or an
        # API-family path prefix
        if not isinstance(s, dict) or not s.get("vendor"):
            raise MalformedSunset(f"sunset entry #{i} has no vendor: {s!r}")
        if not (s.get("version") is not None or s.get("domain") or s.get("operation")
                or s.get("path")):
            raise MalformedSunset(
                f"sunset entry #{i} ({s.get('vendor')}) has no scope — it needs one of "
                f"`version`, `domain`, `operation` or `path`, else it can never match "
                f"anything and would be dropped silently")
        s = dict(s)
        # YAML parses an unquoted date/number as a date/int — coerce so it stays JSON-serializable
        for k in ("version", "domain", "operation", "path", "retires"):
            if s.get(k) is not None:
                s[k] = str(s[k])
        out.append(s)
    return out


def by_vendor(sunsets: list) -> dict:
    idx: dict = defaultdict(list)
    for s in sunsets:
        idx[s["vendor"]].append(s)
    return idx


def status_for(retires, now: str, *, confirmed: bool) -> str:
    """A version we can't confirm the repo is on -> REVIEW. Else past-date -> DEPRECATED,
    future/undated announced retirement -> REVIEW (surface it; lead time is the point)."""
    if not confirmed:
        return "REVIEW"
    if not retires:
        return "DEPRECATED"          # already deprecated, no fixed date
    try:
        return "DEPRECATED" if date.fromisoformat(str(retires)) <= date.fromisoformat(now) else "REVIEW"
    except ValueError:
        return "REVIEW"

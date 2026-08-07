"""The one shared definition of 'worse' (severity) and 'newer' (version).

Both the read facade and the report renderer import these. Keeping one copy is the point:
the ranking logic used to live privately in facade.py, so audit_render.py could not reach it
and ranked nothing at all.
"""
from __future__ import annotations

import re

_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0, "": 0}

# Severities with no CVSS score. Ranked by overdue-ness instead: the audit already decided
# past-due vs approaching when it set `status`, so reuse that rather than re-deriving it.
_DATED_SEVERITIES = {"EOL", "SUNSET"}


def severity_rank(severity, status=None) -> int:
    """Rank a severity; higher is worse. Unknown/None -> 0.

    EOL (dead runtime/framework) and SUNSET (retired vendor API) carry no CVSS score, so they
    are ranked by overdue-ness: past its date (audit marks these DEPRECATED) ranks as HIGH;
    approaching or unconfirmed (REVIEW) ranks as MODERATE.
    """
    sev = str(severity or "").upper()
    if sev in _DATED_SEVERITIES:
        return _SEV_RANK["HIGH"] if status == "DEPRECATED" else _SEV_RANK["MODERATE"]
    return _SEV_RANK.get(sev, 0)


def semver_key(s):
    """Sortable numeric key for a version string. '1.10.0' > '1.7.4' (a string sort gets this
    backwards, which once recommended a lower, still-vulnerable version)."""
    return [int(p) for p in re.findall(r"\d+", str(s))] or [0]


def is_version(s) -> bool:
    """True if s is a real version string, not a git commit SHA or opaque ref.

    OSV.dev returns a commit hash as `fixed` for some advisories; scraping digits out of a
    40-char hex SHA yields a huge sort key that beats every real version, so such values must
    be excluded from fix-version selection.
    """
    s = str(s or "").strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    core = re.split(r"[-+]", s, maxsplit=1)[0]     # drop pre-release/build metadata
    return bool(core) and all(part.isdigit() for part in core.split("."))

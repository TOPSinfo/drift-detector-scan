"""Compute a CVSS v3.x base score + severity label from a vector string.

OSV advisories for PyPI/Packagist often carry only a CVSS vector (no GHSA
`database_specific.severity`), so we derive the severity ourselves to classify
criticals correctly. Non-3.x vectors return None (caller falls back to UNKNOWN).
"""
from __future__ import annotations

import math

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC = {"L": 0.77, "H": 0.44}
_PR_U = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_C = {"N": 0.85, "L": 0.68, "H": 0.5}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"N": 0.0, "L": 0.22, "H": 0.56}


def _roundup(x: float) -> float:
    i = round(x * 100000)
    if i % 10000 == 0:
        return i / 100000.0
    return (math.floor(i / 10000) + 1) / 10.0


def base_score(vector: str) -> float | None:
    if not vector or not vector.startswith(("CVSS:3.0", "CVSS:3.1")):
        return None
    m = {}
    for part in vector.split("/")[1:]:
        k, _, v = part.partition(":")
        m[k] = v
    try:
        scope_changed = m["S"] == "C"
        iss = 1 - (1 - _CIA[m["C"]]) * (1 - _CIA[m["I"]]) * (1 - _CIA[m["A"]])
        impact = (7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15) if scope_changed else 6.42 * iss
        pr = (_PR_C if scope_changed else _PR_U)[m["PR"]]
        expl = 8.22 * _AV[m["AV"]] * _AC[m["AC"]] * pr * _UI[m["UI"]]
    except KeyError:
        return None
    if impact <= 0:
        return 0.0
    raw = 1.08 * (impact + expl) if scope_changed else (impact + expl)
    return _roundup(min(raw, 10.0))


def label(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score == 0:
        return "NONE"
    if score < 4.0:
        return "LOW"
    if score < 7.0:
        return "MODERATE"
    if score < 9.0:
        return "HIGH"
    return "CRITICAL"

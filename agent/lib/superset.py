"""Assemble one per-repo superset record from partitioned manifest records + endpoints."""
from __future__ import annotations

_QUALITY_RANK = {"exact": 3, "unlocked": 2, "best_effort": 1}


def _runtimes(records: list) -> dict:
    out: dict = {}
    for r in records:
        entry = {"range": r.version_hint or r.declared_range,
                 "techKey": r.tech_key, "parseQuality": r.parse_quality}
        cur = out.get(r.name)
        if cur is None or _QUALITY_RANK.get(r.parse_quality, 0) > _QUALITY_RANK.get(cur["parseQuality"], 0):
            out[r.name] = entry
    return out


def to_superset_repo(meta: dict, partitioned: dict, endpoints: list) -> dict:
    return {
        "id": meta.get("id"), "path": meta.get("path"),
        "ref": meta.get("ref"), "ref_is_default": meta.get("ref_is_default"),
        "last_activity_at": meta.get("last_activity_at"), "head_sha": meta.get("head_sha"),
        "remote_url": meta.get("remote_url"),
        "runtimes": _runtimes(partitioned.get("runtimes", [])),
        "frameworks": {r.name: {"ver": r.declared_range, "techKey": r.tech_key,
                                "parseQuality": r.parse_quality}
                       for r in partitioned.get("frameworks", [])},
        "sdks": [{"eco": r.ecosystem, "pkg": r.name, "ver": r.declared_range,
                  "file": r.manifest_path, "techKey": r.tech_key, "parseQuality": r.parse_quality}
                 for r in partitioned.get("sdks", [])],
        "endpoints": endpoints,
        "provenance": meta.get("provenance", {}),
        "tree_walk_truncated": meta.get("tree_walk_truncated", False),
    }

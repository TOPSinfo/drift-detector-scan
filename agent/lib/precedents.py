"""Shape memory — "have we absorbed something like this before, and what closed it?"

Served deterministically by STRUCTURAL BUCKETING, not vectors: a shape's bucket is a stable
tuple of (meaningful languages, residue reasons). Every merged absorption appends one record
to `absorptions.yaml` in the drift-ops overlay (reviewed in the same MR); `drift-scan
precedents` matches a flagged repo's bucket against that log and points the assimilator at the
idiom instances that closed a similar shape. Zero AI, diffable, regenerable from git history —
the reconciliation of the user's "knowledge of the vectors" into knowledge of the precedents.
"""
from __future__ import annotations

import os

import yaml

ABSORPTIONS = "absorptions.yaml"     # lives in the overlay dir alongside *.local.yaml


def bucket_key(shape: dict) -> str:
    """A repo's structural bucket: sorted languages | sorted residue reasons. Two repos with
    the same key are 'the same kind of blind spot' — a PHP config-driven-url repo buckets with
    other PHP config-driven-url repos, whatever their vendor."""
    langs = ",".join(sorted((shape.get("languages") or {}).keys())) or "?"
    reasons = ",".join(sorted(shape.get("reasons") or [])) or "?"
    return f"{langs} | {reasons}"


def record(shape: dict, idiom_ids: list, *, repo: str, date: str,
           attributed_delta: int | None = None) -> dict:
    """One absorption-log entry."""
    r = {"bucket": bucket_key(shape), "repo": repo, "date": date,
         "idioms": sorted(str(i) for i in idiom_ids)}
    if attributed_delta is not None:
        r["attributedDelta"] = attributed_delta
    return r


def load_absorptions(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or []
    except (OSError, ValueError):
        return []


def find_precedents(shape: dict, absorptions: list) -> list:
    """Prior absorptions in the SAME bucket, newest first."""
    b = bucket_key(shape)
    return sorted((a for a in absorptions if a.get("bucket") == b),
                  key=lambda a: str(a.get("date", "")), reverse=True)


def append_absorption(path: str, rec: dict) -> None:
    """Append `rec` to the log, deduped by (repo, idioms) so re-running absorb doesn't pile up
    duplicate entries. Deterministic order (by date, then repo)."""
    existing = load_absorptions(path)
    key = (rec.get("repo"), tuple(rec.get("idioms") or []))
    kept = [a for a in existing if (a.get("repo"), tuple(a.get("idioms") or [])) != key]
    kept.append(rec)
    kept.sort(key=lambda a: (str(a.get("date", "")), str(a.get("repo", ""))))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(kept, fh, sort_keys=True, allow_unicode=True)

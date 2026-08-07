"""Give audit findings an identity and a memory, so the report shows what's NEW/RESOLVED
since last time instead of re-screaming the same list every run.

- fingerprint: stable, VERSION-INDEPENDENT id (repo | kind | ref | cve-id-or-product), so a
  fix makes a finding disappear (resolved) and a still-vulnerable bump persists.
- findings-state.json: fingerprint -> {first_seen, last_seen, ...}, advanced each run.
- audit-baseline.json: fingerprints the team has accepted -> muted (dropped from action counts).
"""
from __future__ import annotations

import hashlib
import json
import os

from agent.lib.actions import build_actions

STATE_NAME = "findings-state.json"
BASELINE_NAME = "audit-baseline.json"


def fingerprint(f: dict) -> str:
    kind = f.get("kind")
    if kind == "cve":
        ident = f.get("id") or f.get("cve") or ""          # version-independent (a fix resolves it)
    elif kind == "sunset":
        ident = f"{f.get('ref')}|{f.get('version')}"       # a specific API version's retirement
        if f.get("domain"):                                # domain-scoped: keep hosts distinct
            ident += f"|{f.get('domain')}"
    else:                                                   # eol: the product line
        ident = f.get("ref", "")
    raw = f"{f.get('repo')}|{kind}|{f.get('ref')}|{ident}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return None


def _save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)


def load_baseline(state_dir: str) -> set:
    return set(_load(os.path.join(state_dir, BASELINE_NAME)) or [])


def add_to_baseline(state_dir: str, fps) -> None:
    cur = load_baseline(state_dir)
    cur.update([fps] if isinstance(fps, str) else fps)
    _save(os.path.join(state_dir, BASELINE_NAME), sorted(cur))


def remove_from_baseline(state_dir: str, fps) -> None:
    cur = load_baseline(state_dir)
    cur.difference_update([fps] if isinstance(fps, str) else fps)
    _save(os.path.join(state_dir, BASELINE_NAME), sorted(cur))


def apply_lifecycle(audit: dict, state_dir: str, now: str) -> dict:
    """Annotate findings with fingerprint/first_seen/suppressed, compute delta, advance state,
    and recompute counts excluding muted findings. Mutates and returns `audit`."""
    findings = audit.get("findings", [])
    prior = _load(os.path.join(state_dir, STATE_NAME)) or {}
    baseline = load_baseline(state_dir)

    new, muted, seen = [], [], set()
    next_state = {}
    for f in findings:
        fp = fingerprint(f)
        f["fingerprint"] = fp
        seen.add(fp)
        entry = prior.get(fp)
        f["first_seen"] = entry.get("first_seen", now) if entry else now
        # keep muted findings in state too, so un-muting restores their history (not re-alarmed as new)
        next_state[fp] = {"first_seen": f["first_seen"], "last_seen": now,
                          "ref": f.get("ref"), "kind": f.get("kind"), "status": f.get("status")}
        if fp in baseline:
            f["suppressed"] = True
            muted.append(f)
            continue
        if not entry:
            new.append(f)

    resolved = [{"fingerprint": fp, **entry} for fp, entry in prior.items()
                if fp not in seen and fp not in baseline]

    _save(os.path.join(state_dir, STATE_NAME), next_state)

    active = [f for f in findings if not f.get("suppressed")]
    new_fps = {f["fingerprint"] for f in new}
    audit["delta"] = {
        "new": new,
        "resolved": resolved,
        "persisting": [f for f in active if f["fingerprint"] not in new_fps],
        "mutedCount": len(muted),
    }
    audit["counts"] = {
        "DEPRECATED": sum(1 for f in active if f["status"] == "DEPRECATED"),
        "REVIEW": sum(1 for f in active if f["status"] == "REVIEW"),
        "reposAffected": len({f["repo"] for f in active}),
        "new": len(new), "resolved": len(resolved), "muted": len(muted),
    }
    audit["actions"] = build_actions(active)      # ranked jobs; `findings` stays untouched for SARIF/BOM
    return audit

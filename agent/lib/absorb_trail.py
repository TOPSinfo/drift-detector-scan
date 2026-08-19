"""An append-only record of `absorb --check` attempts — the climb, kept.

WHY THIS EXISTS: the absorb loop (commands/drift-absorb.md §3) already computes a complete
before/after on every attempt — attributed call-sites, residue, claims met/missing, gate
problems — prints it, and discards it. So an iterating agent cannot tell convergence from
oscillation, and after a session nobody can show that absorption achieved anything. Everything
needed was already measured; only the persistence was missing.

WHAT THIS IS NOT: it is a debugging by-product, never part of the certified path. `verify` does
not read it, it cannot influence drift.json, and `append` never raises into its caller — if the
file cannot be written, the gate's verdict still stands. A by-product may not break the product.

CLIENT DATA: rows carry repo identities and file:line locations. The file lives in the state
directory (gitignored locally, private drift-ops for a fleet) and `forget` exists so it can be
pruned once the reviewed catalog entry — the artifact actually worth keeping — is merged.
"""
from __future__ import annotations

import json
import os

FILENAME = "absorb-trail.jsonl"


def _path(state_dir: str) -> str:
    return os.path.join(state_dir, FILENAME)


def read(state_dir: str, repo: str | None = None) -> list:
    """Every recorded attempt, oldest first; optionally just one repo's.

    A missing trail is an empty list, not an error — asking about a repo nobody has absorbed is
    a normal question. A corrupt LINE is skipped rather than fatal: this is a hand-editable
    debugging file, and losing one row must not stop the rest from rendering.
    """
    rows = []
    try:
        with open(_path(state_dir), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and (repo is None or row.get("repo") == repo):
                    rows.append(row)
    except OSError:
        return []
    return rows


def append(state_dir: str, *, repo: str, staged: list, delta: dict, now: str | None) -> bool:
    """Record one attempt. Returns True if written, False if it could not be — NEVER raises.

    `attempt` is derived by counting this repo's existing rows, so the file is its own counter
    and nothing else has to hold state. `now` is written exactly as given (None stays None):
    inventing a wall-clock timestamp here would make the file unreproducible and break the
    determinism rule the rest of the pipeline keeps.
    """
    try:
        attempt = len(read(state_dir, repo=repo)) + 1
        row = {"now": now, "repo": repo, "attempt": attempt, "staged": list(staged or []),
               "delta": delta, "verdict": "reject" if (delta or {}).get("problems") else "pass"}
        os.makedirs(state_dir, exist_ok=True)
        with open(_path(state_dir), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except (OSError, TypeError, ValueError):
        return False

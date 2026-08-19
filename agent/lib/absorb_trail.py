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

    `errors="replace"` on the open: a process killed mid-write can truncate a multi-byte
    character, leaving a line that is not valid UTF-8 at all. `for line in fh` decodes as it
    iterates — before the per-line json.loads try below — and a raw UnicodeDecodeError there is
    not an OSError, so it would slip past the `except OSError` and crash the caller. Replacing
    undecodable bytes with U+FFFD keeps decoding infallible; the mangled line then simply fails
    json.loads and is skipped by the existing per-line handling, same as any other corrupt line.
    """
    rows = []
    try:
        with open(_path(state_dir), encoding="utf-8", errors="replace") as fh:
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

    KNOWN LIMITATION, accepted rather than fixed: counting rows for the attempt number means
    numbering is not stable across a later `forget` prune (attempt 3 can become attempt 1 once
    earlier rows are gone), and two concurrent appenders can race and both compute the same
    count, colliding on one attempt number. This is a single-agent debugging file, not a
    multi-writer ledger — no locking is added here on purpose; that would be over-engineering
    for what this file is for.
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

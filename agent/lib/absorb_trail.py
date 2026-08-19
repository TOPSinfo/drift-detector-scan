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


def render(rows: list) -> str:
    """The climb, as Markdown — one table per repo, one row per attempt.

    These are the gate's OWN numbers, replayed, not a re-derivation that could disagree with the
    verdict it gave. That is the whole value: it is evidence, not a summary.
    """
    if not rows:
        # Not an empty table: absence must not read as health. That confusion is the exact
        # failure mode this project exists to prevent, and it applies to its own debug output.
        return "# Absorb trail\n\nNo attempts recorded.\n"
    by_repo: dict = {}
    for r in rows:
        by_repo.setdefault(r.get("repo", "?"), []).append(r)
    out = ["# Absorb trail", ""]
    for repo in sorted(by_repo):
        attempts = sorted(by_repo[repo], key=lambda r: r.get("attempt", 0))
        passed = any(a.get("verdict") == "pass" for a in attempts)
        out += [f"## {repo} — {len(attempts)} attempts, "
                f"{'PASSED' if passed else 'not yet passing'}", "",
                "| # | staged | attributed | residue | claims | verdict |",
                "|---|--------|-----------|---------|--------|---------|"]
        for a in attempts:
            d = a.get("delta") or {}
            claims = d.get("claims") or {}
            met, miss = len(claims.get("met") or []), len(claims.get("missing") or [])
            problems = d.get("problems") or []
            verdict = "**pass**" if a.get("verdict") == "pass" else \
                      f"reject — {problems[0]}" if problems else "reject"
            out.append(
                f"| {a.get('attempt')} | {len(a.get('staged') or [])} | "
                f"{d.get('attributedBefore')} → {d.get('attributedAfter')} | "
                f"{d.get('residueBefore')} → {d.get('residueAfter')} | "
                f"{met}/{met + miss} | {verdict} |")
        out.append("")
    return "\n".join(out) + "\n"


def forget(state_dir: str, repo: str) -> int:
    """Drop one repo's attempts; returns how many rows went. Returns 0 if there is no trail.

    Meant as habit, not housekeeping: once a repo's idiom is merged into the reviewed catalog,
    the attempts that produced it have no further value — and they are the part carrying client
    file:line data. The catalog entry is the artifact worth keeping.
    """
    kept = [r for r in read(state_dir) if r.get("repo") != repo]
    removed = len(read(state_dir)) - len(kept)
    if removed:
        with open(_path(state_dir), "w", encoding="utf-8") as fh:
            for r in kept:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    return removed

# Absorb Trail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every `absorb --check` attempt to an append-only trail, and render it as the "climb" — so a session's before/after is reviewable afterwards instead of vanishing off stdout.

**Architecture:** A new pure module `agent/lib/absorb_trail.py` owns the file format (append, read, prune, render). `agent/cli.py` calls it from two places: the existing `absorb --check` branch when `--trail` is passed, and a new `absorb-report` subcommand. Nothing else in the pipeline learns the trail exists.

**Tech Stack:** Python 3 (stdlib + PyYAML only at runtime), pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-absorb-trail-design.md`

## Global Constraints

- Runtime dependencies are **stdlib + PyYAML only**. `jsonschema` is test-only.
- The scan path is **deterministic**. `now` is passed in — **never** read the wall clock.
- **`verify` must never read the trail**, and the trail must never influence `drift.json`.
- **A trail failure must never fail an absorb.** Warn and continue; the gate's verdict is the product.
- The trail is **client data** (`file:line`s, repo identities) — gitignored, prunable, never committed.
- Comments are load-bearing: each explains *why*, and where a comment pins a real bug it says so.
- **Every guard must be shown to FAIL on the bug it targets** (CLAUDE.md principle 5).
- Test baseline: `.venv/bin/python -m pytest -q` — **1346 passed, 3 skipped** at plan time.

## File structure

| file | responsibility |
|---|---|
| `agent/lib/absorb_trail.py` | **new** — the only module that knows the file format: `append`, `read`, `forget`, `render` |
| `tests/test_absorb_trail.py` | **new** — unit tests for that module |
| `agent/cli.py` | wires `--trail` into the existing `--check` branch; adds the `absorb-report` subcommand |
| `commands/drift-absorb.md` | passes `--trail` in the loop |
| `tests/test_promptfile_discipline.py` | pins that the promptfile passes `--trail` |
| `.gitignore` | ignores `absorb-trail.jsonl` |

---

### Task 1: The trail module — append and read

**Files:**
- Create: `agent/lib/absorb_trail.py`
- Test: `tests/test_absorb_trail.py`

**Interfaces:**
- Produces: `append(state_dir, *, repo, staged, delta, now) -> bool` (True if written, False if it could not be — never raises) and `read(state_dir, repo=None) -> list[dict]`. Task 2 calls `append`; Tasks 3 and 4 call `read`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_absorb_trail.py`:

```python
"""The absorb trail: an append-only record of what each `absorb --check` attempt achieved.

The gate already computes a complete before/after per attempt and throws it away, so a session
leaves no evidence and an iterating agent cannot tell convergence from oscillation. This module
is the persistence, and these tests pin the properties that make it safe to add: it never raises
into the caller, and it never becomes something the certified path depends on.
"""
import json
import os

from agent.lib import absorb_trail


def _delta(attributed_after=44, problems=None):
    return {"attributedBefore": 0, "attributedAfter": attributed_after,
            "residueBefore": 51, "residueAfter": 7,
            "claims": {"met": ["a.php:1"], "missing": []},
            "invented": [], "unclaimed": [], "problems": problems or []}


def test_append_writes_one_line_per_attempt_numbered_in_order(tmp_path):
    for i in range(3):
        assert absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1"],
                                   delta=_delta(), now="2026-08-19") is True
    rows = absorb_trail.read(str(tmp_path))
    assert [r["attempt"] for r in rows] == [1, 2, 3]
    assert all(r["repo"] == "acme/api" for r in rows)


def test_attempt_numbering_is_per_repo_not_global(tmp_path):
    absorb_trail.append(str(tmp_path), repo="acme/one", staged=[], delta=_delta(), now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="acme/two", staged=[], delta=_delta(), now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="acme/one", staged=[], delta=_delta(), now="2026-08-19")
    assert [r["attempt"] for r in absorb_trail.read(str(tmp_path), repo="acme/one")] == [1, 2]
    assert [r["attempt"] for r in absorb_trail.read(str(tmp_path), repo="acme/two")] == [1]


def test_verdict_is_pass_only_when_there_are_no_problems(tmp_path):
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(problems=["bad"]),
                        now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(), now="2026-08-19")
    assert [r["verdict"] for r in absorb_trail.read(str(tmp_path))] == ["reject", "pass"]


def test_now_is_recorded_as_given_and_never_invented(tmp_path):
    # Determinism: `now` is passed in throughout this codebase. A trail that filled in the wall
    # clock would make the file unreproducible and quietly break that rule.
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(), now=None)
    assert absorb_trail.read(str(tmp_path))[0]["now"] is None


def test_append_returns_false_instead_of_raising_when_it_cannot_write(tmp_path):
    # THE BUG THIS GUARDS: a by-product may not break the product. If the trail cannot be
    # written, `absorb --check` must still report its verdict and exit code unchanged.
    unwritable = tmp_path / "nope"
    unwritable.write_text("i am a file, not a directory")
    assert absorb_trail.append(str(unwritable), repo="r", staged=[], delta=_delta(),
                               now="2026-08-19") is False


def test_read_ignores_a_corrupt_line_rather_than_dying(tmp_path):
    # A hand-edited or truncated trail is a debugging file, not a contract. Losing one line is
    # acceptable; refusing to render anything is not.
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(), now="2026-08-19")
    with open(os.path.join(str(tmp_path), absorb_trail.FILENAME), "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    assert len(absorb_trail.read(str(tmp_path))) == 1


def test_read_of_a_missing_trail_is_empty_not_an_error(tmp_path):
    assert absorb_trail.read(str(tmp_path)) == []


def test_the_written_line_carries_the_gate_delta_verbatim(tmp_path):
    d = _delta()
    absorb_trail.append(str(tmp_path), repo="r", staged=["i/1", "i/2"], delta=d, now="2026-08-19")
    row = absorb_trail.read(str(tmp_path))[0]
    assert row["delta"] == d, "the trail must record the gate's own numbers, not a re-derivation"
    assert row["staged"] == ["i/1", "i/2"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.absorb_trail'`

- [ ] **Step 3: Create the module**

Create `agent/lib/absorb_trail.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Prove the never-raises guard fails on its bug**

Temporarily change `append`'s `except (OSError, TypeError, ValueError): return False` to `raise`, then run:

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -q`
Expected: **FAIL** on `test_append_returns_false_instead_of_raising_when_it_cannot_write` — proving the guard is load-bearing. Restore the `except` and re-run: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/absorb_trail.py tests/test_absorb_trail.py
git commit -m "feat(absorb-trail): the append-only attempt record

The absorb loop computes a complete before/after per attempt and discards it.
This is the persistence. append() never raises into its caller — a debugging
by-product may not break the gate it observes — and `now` is written as given
so the file stays reproducible."
```

---

### Task 2: Wire `--trail` into `absorb --check`

**Files:**
- Modify: `agent/cli.py` — the `absorb` parser (around line 1574) and the `--check` branch (line 993-1013)
- Test: `tests/test_absorb_trail.py`

**Interfaces:**
- Consumes: `absorb_trail.append(state_dir, *, repo, staged, delta, now) -> bool` from Task 1.
- Produces: `absorb --check --trail` writes one row per invocation. `--check` **without** `--trail` still writes nothing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_absorb_trail.py`:

```python
def test_check_without_trail_writes_nothing(tmp_path, monkeypatch):
    """PURITY. `absorb --check` is documented as a dry run that writes nothing in TWO places —
    commands/drift-absorb.md and agent/absorb.py's docstring. The trail is opt-in precisely so
    that stays true; this pins it against a future change that makes writing the default."""
    from agent import cli
    calls = []
    monkeypatch.setattr(absorb_trail, "append", lambda *a, **k: calls.append(k) or True)
    args = _FakeArgs(state=str(tmp_path), trail=False)
    cli._maybe_record_trail(args, repo="r", staged=[], delta=_delta())
    assert calls == []
    assert not os.path.exists(os.path.join(str(tmp_path), absorb_trail.FILENAME))


def test_check_with_trail_records_one_row(tmp_path):
    from agent import cli
    args = _FakeArgs(state=str(tmp_path), trail=True, now="2026-08-19")
    cli._maybe_record_trail(args, repo="acme/api", staged=["i/1"], delta=_delta())
    rows = absorb_trail.read(str(tmp_path))
    assert len(rows) == 1 and rows[0]["repo"] == "acme/api" and rows[0]["attempt"] == 1


def test_trail_without_state_is_a_warning_not_a_crash(tmp_path, capsys):
    """--trail needs somewhere to write. Saying so beats writing nowhere silently."""
    from agent import cli
    args = _FakeArgs(state=None, trail=True)
    cli._maybe_record_trail(args, repo="r", staged=[], delta=_delta())
    assert "trail" in capsys.readouterr().err.lower()


class _FakeArgs:
    def __init__(self, **kw):
        self.state = kw.get("state")
        self.trail = kw.get("trail", False)
        self.now = kw.get("now")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -k "trail_records or without_trail or without_state" -q`
Expected: FAIL — `AttributeError: module 'agent.cli' has no attribute '_maybe_record_trail'`

- [ ] **Step 3: Add the helper to `agent/cli.py`**

Insert immediately **before** `def _cmd_absorb(` in `agent/cli.py`:

```python
def _maybe_record_trail(args, *, repo: str, staged: list, delta: dict) -> None:
    """Record this --check attempt to the absorb trail, if --trail was asked for.

    Opt-in on purpose: `absorb --check` is documented as writing nothing (commands/
    drift-absorb.md and absorb.py's docstring both say so), and quietly falsifying that is the
    drift this project spends its effort preventing. Failures here are warnings, never errors —
    the gate's verdict is the product and a debugging by-product may not break it.
    """
    if not getattr(args, "trail", False):
        return
    if not getattr(args, "state", None):
        print("absorb: --trail needs --state; no trail written", file=sys.stderr)
        return
    from agent.lib import absorb_trail
    if not absorb_trail.append(args.state, repo=repo, staged=staged, delta=delta,
                               now=getattr(args, "now", None)):
        print("absorb: could not write the trail (continuing — the verdict is unaffected)",
              file=sys.stderr)
```

- [ ] **Step 4: Call it from the `--check` branch**

In `agent/cli.py`, in the `if getattr(args, "check", False):` block, replace this line:

```python
        return 3 if m["problems"] else 0
```

with:

```python
        _maybe_record_trail(args, repo=repo_ident,
                            staged=[i.get("id") for i in (staged_idioms or [])],
                            delta={k: m[k] for k in
                                   ("attributedBefore", "attributedAfter", "residueBefore",
                                    "residueAfter", "claims", "invented", "unclaimed",
                                    "problems")})
        return 3 if m["problems"] else 0
```

- [ ] **Step 5: Register the flag**

In `agent/cli.py`, after the `pab.add_argument("--check", ...)` block, add:

```python
    pab.add_argument("--trail", action="store_true",
                     help="with --check: append this attempt to <state>/absorb-trail.jsonl so "
                          "the climb can be reviewed later (a debug by-product; --check "
                          "without it still writes nothing)")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -q`
Expected: PASS (11 tests)

- [ ] **Step 7: Prove the purity guard fails on its bug**

Temporarily change `_maybe_record_trail`'s first line to `if False:` (making the trail always write), then run:

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -k without_trail -q`
Expected: **FAIL** — proving the purity test would catch a change that makes writing the default. Restore `if not getattr(args, "trail", False):` and re-run: PASS.

- [ ] **Step 8: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected 1346 + 11 new = **1357 passed, 3 skipped**. Any DROP is a regression.

```bash
git add agent/cli.py tests/test_absorb_trail.py
git commit -m "feat(absorb): --trail records each --check attempt

Opt-in, because --check is documented as pure in two places and quietly
falsifying that is the drift this project prevents. A trail failure warns and
continues: the gate's verdict is the product."
```

---

### Task 3: `absorb-report` — render the climb, and prune

**Files:**
- Modify: `agent/lib/absorb_trail.py` (add `render` and `forget`)
- Modify: `agent/cli.py` (add the `absorb-report` subcommand)
- Test: `tests/test_absorb_trail.py`

**Interfaces:**
- Consumes: `read(state_dir, repo=None)` from Task 1.
- Produces: `render(rows) -> str` (Markdown) and `forget(state_dir, repo) -> int` (rows removed).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_absorb_trail.py`:

```python
def test_render_shows_each_attempt_as_a_row(tmp_path):
    absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1"],
                        delta=_delta(attributed_after=0, problems=["no claim met"]),
                        now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1", "i/2"],
                        delta=_delta(), now="2026-08-19")
    out = absorb_trail.render(absorb_trail.read(str(tmp_path)))
    assert "acme/api" in out
    assert "0 → 0" in out and "0 → 44" in out       # the climb is visible
    assert "reject" in out and "pass" in out
    assert "2 attempts" in out


def test_render_of_no_attempts_says_so_rather_than_looking_clean(tmp_path):
    # THE BUG THIS GUARDS: an empty table reads as "nothing went wrong". "No attempts recorded"
    # reads as what it is. This project's whole thesis is that absence must not look like health.
    out = absorb_trail.render([])
    assert "no attempts recorded" in out.lower()
    assert "|" not in out, "an empty table would imply a session that produced nothing to fix"


def test_forget_removes_only_the_named_repo(tmp_path):
    absorb_trail.append(str(tmp_path), repo="keep/me", staged=[], delta=_delta(), now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="drop/me", staged=[], delta=_delta(), now="2026-08-19")
    assert absorb_trail.forget(str(tmp_path), "drop/me") == 1
    remaining = absorb_trail.read(str(tmp_path))
    assert [r["repo"] for r in remaining] == ["keep/me"]


def test_forget_of_an_unknown_repo_removes_nothing(tmp_path):
    absorb_trail.append(str(tmp_path), repo="keep/me", staged=[], delta=_delta(), now="2026-08-19")
    assert absorb_trail.forget(str(tmp_path), "never/absorbed") == 0
    assert len(absorb_trail.read(str(tmp_path))) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -k "render or forget" -q`
Expected: FAIL — `AttributeError: module 'agent.lib.absorb_trail' has no attribute 'render'`

- [ ] **Step 3: Add `render` and `forget` to `agent/lib/absorb_trail.py`**

Append to the module:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -q`
Expected: PASS (15 tests)

- [ ] **Step 5: Add the `absorb-report` subcommand**

In `agent/cli.py`, add this function immediately before `_maybe_record_trail`:

```python
def _cmd_absorb_report(args) -> int:
    """Render the absorb trail — the climb across attempts — or prune one repo's rows.

    A debug projection, deliberately outside the certified path: it reads only the trail, and
    `verify` never reads it back. Exit 0 always; there is no failure state in reading a record.
    """
    from agent.lib import absorb_trail
    if getattr(args, "forget", None):
        n = absorb_trail.forget(args.state, args.forget)
        print(f"absorb-report: removed {n} attempt(s) for {args.forget}")
        return 0
    print(absorb_trail.render(absorb_trail.read(args.state, repo=getattr(args, "repo", None))))
    return 0
```

And register it next to the other subcommands, immediately after the `absorb` parser block:

```python
    par2 = sub.add_parser("absorb-report")   # the absorb trail -> Markdown (debug projection)
    par2.add_argument("--state", required=True)
    par2.add_argument("--repo", help="only this repo's attempts")
    par2.add_argument("--forget", help="drop this repo's attempts (do it once its idiom merges)")
    par2.set_defaults(func=_cmd_absorb_report)
```

- [ ] **Step 6: Verify the command end-to-end**

```bash
rm -rf /tmp/trail-demo && mkdir -p /tmp/trail-demo
.venv/bin/python - <<'PY'
from agent.lib import absorb_trail
d = lambda a, p=None: {"attributedBefore": 0, "attributedAfter": a, "residueBefore": 51,
                       "residueAfter": 51 - a, "claims": {"met": [], "missing": ["x"]},
                       "invented": [], "unclaimed": [], "problems": p or []}
absorb_trail.append("/tmp/trail-demo", repo="acme/api", staged=["i/1"], delta=d(0, ["no claim met"]), now="2026-08-19")
absorb_trail.append("/tmp/trail-demo", repo="acme/api", staged=["i/1","i/2"], delta=d(44), now="2026-08-19")
PY
./bin/drift-scan absorb-report --state /tmp/trail-demo
```
Expected: a table with two rows, `0 → 0` then `0 → 44`, verdicts `reject — no claim met` and `**pass**`.

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected **1361 passed, 3 skipped**.

```bash
git add agent/lib/absorb_trail.py agent/cli.py tests/test_absorb_trail.py
git commit -m "feat(absorb-report): render the climb, and prune it

Replays the gate's own numbers rather than re-deriving them, so the table
cannot disagree with the verdict it reports. An empty trail says 'no attempts
recorded' rather than rendering an empty table, because absence must not read
as health — including in this tool's own debug output."
```

---

### Task 4: Close the boundaries — gitignore, verify independence, promptfile

**Files:**
- Modify: `.gitignore`
- Modify: `commands/drift-absorb.md:76`
- Test: `tests/test_absorb_trail.py`, `tests/test_promptfile_discipline.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: nothing new — this task makes the spec's four boundaries enforced rather than intended.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_absorb_trail.py`:

```python
import subprocess


def test_the_trail_filename_is_gitignored(tmp_path):
    """It carries client file:line data and repo identities. Being gitignored is the mechanism
    that keeps it out of a public tree; a comment asking people to be careful is not."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(["git", "check-ignore", "-q", absorb_trail.FILENAME],
                         cwd=root).returncode
    assert out == 0, f"{absorb_trail.FILENAME} must be gitignored — it is client data"


def test_verify_does_not_read_the_trail():
    """BOUNDARY: a debugging by-product must never become something the correctness claim rests
    on. If verify learned to read the trail, deleting a debug file could change whether a report
    is judged correct."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "agent", "lib", "verify.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "absorb_trail" not in src and absorb_trail.FILENAME not in src
```

In `tests/test_promptfile_discipline.py`, first widen the module docstring — its last line
currently claims the file covers `/drift-research` only, and leaving that while adding an absorb
test would make the file misdescribe itself. Change:

```
This file covers `/drift-research` — the loop most exposed to "just make up a plausible date," which
had no guard.
```

to:

```
This file covers `/drift-research` — the loop most exposed to "just make up a plausible date," which
had no guard — and `/drift-absorb`, whose loop must keep recording its trail.
```

Then append (note the file locates promptfiles via `_CMD`, not `ROOT`):

```python
def test_absorb_loop_records_its_trail():
    """The loop must pass --trail, or the record silently does not happen — the same
    silent-skip failure the client-identifier guard had. The flag is opt-in to keep
    `absorb --check` pure; this is what stops opt-in becoming never-on."""
    t = (_CMD / "drift-absorb.md").read_text()
    assert "--trail" in t, "the absorb loop must pass --trail so the climb is recorded"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -k "gitignored or verify_does_not" tests/test_promptfile_discipline.py -k "records_its_trail" -q`
Expected: FAIL — the gitignore entry and the `--trail` flag in the promptfile do not exist yet.

- [ ] **Step 3: Add the gitignore entry**

Append to `.gitignore`:

```
# the absorb trail — a debug by-product carrying client repo ids and file:line data.
# Ignored by NAME so it is covered wherever a --state dir happens to live.
absorb-trail.jsonl
```

- [ ] **Step 4: Update the promptfile**

In `commands/drift-absorb.md`, change line 76 from:

```
  "$SCAN" absorb --check --staged "$D/absorb-staged" --repo "$REPO" --state "$D" --now "$(date +%F)"
```

to:

```
  "$SCAN" absorb --check --trail --staged "$D/absorb-staged" --repo "$REPO" --state "$D" --now "$(date +%F)"
```

And in the same file, change the sentence on line 71 from "a dry run that reports the attributed-call delta and writes nothing" to:

```
This is the assimilation. Iterate with **`absorb --check`** — a dry run that reports the attributed-call delta and touches neither the catalog nor the report (`--trail` appends this attempt to `<state>/absorb-trail.jsonl` so the climb can be reviewed afterwards; without it, nothing is written at all):
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py tests/test_promptfile_discipline.py -q`
Expected: PASS

- [ ] **Step 6: Prove the gitignore guard fails on its bug**

Temporarily remove the `absorb-trail.jsonl` line from `.gitignore`, then run:

Run: `.venv/bin/python -m pytest tests/test_absorb_trail.py -k gitignored -q`
Expected: **FAIL** — proving the guard would catch its removal. Restore the line and re-run: PASS.

- [ ] **Step 7: Confirm `verify` still passes with no trail, and with a corrupt one**

```bash
rm -rf /tmp/trail-verify
./bin/drift-scan run --root . --state /tmp/trail-verify --now "$(date +%F)" >/dev/null 2>&1
./bin/drift-scan verify --state /tmp/trail-verify >/dev/null 2>&1; echo "no trail:      EXIT=$?"
echo "{not json" > /tmp/trail-verify/absorb-trail.jsonl
./bin/drift-scan verify --state /tmp/trail-verify >/dev/null 2>&1; echo "corrupt trail: EXIT=$?"
```
Expected: **both `EXIT=0`** — the trail is genuinely outside the correctness claim.

- [ ] **Step 8: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected **1364 passed, 3 skipped**.

```bash
git add .gitignore commands/drift-absorb.md tests/test_absorb_trail.py tests/test_promptfile_discipline.py
git commit -m "feat(absorb-trail): enforce the boundaries

Gitignored by name (client file:line data), a test asserting verify never
reads it, and a promptfile-discipline test pinning that the loop passes
--trail — so opt-in cannot quietly become never-on. Verified verify exits 0
both with no trail and with a deliberately corrupt one."
```

---

## Notes for the implementer

- **Run with `DRIFT_CATALOG_DIR=""`** for any scan you do while testing. The default overlay is `~/.drift/catalog`, which on this machine holds private hand-authored idioms that would contaminate results.
- **Do not add the trail to `verify`.** Task 4 has a test asserting it is absent; that test is the point, not an obstacle.
- The spec's fourth boundary — a trail failure must never fail an absorb — is carried by `append` returning `False` (Task 1) and `_maybe_record_trail` warning rather than raising (Task 2). Both are pinned by tests.

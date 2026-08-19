# Absorb trail — a record of the climb

**Date:** 2026-08-19
**Status:** approved in outline, spec for review
**Origin:** questions from a product demo — "show before/after of what it did" and "we only see
the latest thing, we need a trail"

## The problem

`commands/drift-absorb.md` §3 is called *"The loop — climb the delta"*. It is a real loop:

1. stage idioms → 2. run `absorb --check` → 3. read the `DELTA {json}` → 4. repeat

Every iteration already computes a complete, machine-checked before/after
(`agent/absorb.py`, printed at `agent/cli.py:995-1012`):

```
{attributedBefore, attributedAfter, residueBefore, residueAfter,
 claims: {met, missing}, invented, unclaimed, problems}
```

And then throws it away. The consequences:

- **Claude cannot tell convergence from oscillation.** It sees attempt *N* but not attempts
  1…*N-1*, so "this is the third time I have tried a variant of this regex" is invisible to it.
- **Nobody can show that absorption worked.** The proof exists for one second on stdout.
- **A session leaves no record.** After a day of absorption runs there is nothing to review.

This is not a measurement gap. Everything needed is already computed. It is a persistence gap.

## Non-goals

- **Not** a general run-history layer for the fleet report. Week-over-week trend rendering is a
  separate, larger piece and remains the first item on `docs/ROADMAP.md`.
- **Not** part of the certified path. See "Boundaries".
- **No screenshots.** The demo asked for them; rendering the diff as verified text is better —
  it can be checked, diffed, and does not put a headless browser into a stdlib-only runtime.

## Design

### 1. The trail file

`<state>/absorb-trail.jsonl` — append-only, one JSON object per `absorb --check` invocation:

```json
{"now": "2026-08-19", "repo": "<repo scope id>", "attempt": 3,
 "staged": ["adhoc/acme-api/1", "adhoc/acme-api/2"],
 "delta": {"attributedBefore": 0, "attributedAfter": 44,
           "residueBefore": 51, "residueAfter": 7,
           "claims": {"met": [...], "missing": []},
           "invented": [], "unclaimed": [], "problems": []},
 "verdict": "pass"}
```

- `attempt` is derived by counting existing lines for that `repo`, so it needs no state of its own.
- `verdict` is `"pass"` when `problems` is empty, `"reject"` otherwise — the same condition the
  exit code already uses.
- `now` comes from `--now`, never from the clock, so the file stays reproducible. When `--now`
  is absent the key is written as `null` rather than being filled in from the wall clock.

**Written only when `--trail` is passed**, alongside `--state`.

An earlier draft of this spec had it write on every `--check` with a `--state`, reasoning that a
flag the promptfile forgets is a trail that silently does not exist. Reviewing it against the
code killed that: `absorb --check` is documented as pure in **two** places —
`commands/drift-absorb.md:71` ("a dry run that reports the attributed-call delta and writes
nothing") and `agent/absorb.py:157` ("Pure: writes nothing"). Quietly making the dry run write
to disk would falsify both, and "the docs said it was pure" is precisely the class of drift this
project spends its effort preventing.

The forgotten-flag risk is real but guardable, and cheaper than losing the invariant:
`tests/test_promptfile_discipline.py` already pins load-bearing promptfile rules, so a test
asserts `commands/drift-absorb.md` passes `--trail`. The flag also makes the debug intent
explicit at the call site, which is what the demo actually asked for.

### 2. The report

`drift-scan absorb-report --state <dir> [--repo <id>]` renders the trail as Markdown:

```
## acme/acme-api — 4 attempts, PASSED

| # | staged | attributed | residue | claims | verdict |
|---|--------|-----------|---------|--------|---------|
| 1 | 1 idiom  | 0 → 0   | 51 → 51 | 0/3 | reject — no claim met |
| 2 | 1 idiom  | 0 → 12  | 51 → 39 | 1/3 | reject — 2 claims missing |
| 3 | 2 idioms | 0 → 44  | 51 → 7  | 3/3 | reject — 1 unclaimed attribution |
| 4 | 2 idioms | 0 → 44  | 51 → 7  | 3/3 | **pass** |
```

That table is the before/after proof the demo asked for, and it is the same numbers the gate
used — not a re-derivation that could disagree with it.

### 3. Pruning

`drift-scan absorb-report --state <dir> --forget <repo>` drops that repo's lines.

Intended as habit, not housekeeping: once a repo's idiom is merged into the catalog, the
attempts that produced it have no further value, and they are the part that carries client
`file:line`s. The reviewed catalog entry is the artifact worth keeping.

## Boundaries

These are what keep a debugging aid from becoming something the correctness claim rests on.

1. **`verify` must never read the trail.** A missing or corrupt trail must not affect whether a
   report is judged correct.
2. **The trail must never influence `drift.json`.** Same firewall as AI leads.
3. **It is client data.** `file:line`s and repo identities. It lives in the state directory —
   gitignored locally, and in the private drift-ops repo for the fleet. `absorb-trail.jsonl` is
   added to `.gitignore`, with a test asserting it is ignored, so this is enforced rather than
   remembered.
4. **A trail failure must never fail an absorb.** If the file cannot be written, `absorb --check`
   prints a warning and continues. The gate's verdict is the product; the trail is a by-product,
   and a by-product may not break the product.

## Testing

Per CLAUDE.md principle 5, each guard is shown to fail on its bug:

- appending N attempts yields N lines with `attempt` 1…N, in order
- a repo with no trail renders as "no attempts recorded", not an error or an empty table that
  reads as success
- `--forget` removes only the named repo's lines and leaves others intact
- an unwritable trail path leaves `absorb --check`'s exit code and `DELTA` output unchanged
  (prove by pointing `--state` at a read-only directory)
- `verify` passes on a state directory whose trail has been deleted, and on one with a
  deliberately corrupt line
- the `.gitignore` entry is asserted by test, and the test is shown to fail when it is removed
- **`absorb --check` without `--trail` writes nothing** — the purity both docs promise, pinned so
  a future change cannot quietly break it
- `commands/drift-absorb.md` passes `--trail` (promptfile-discipline test), so the loop cannot
  silently stop recording

## Open questions

1. **The promptfile needs one edit**: `commands/drift-absorb.md:76` already passes
   `--state "$D" --now "$(date +%F)"`, so it gains `--trail` and nothing else changes. Whether
   the loop should also *read* the trail — "you have tried this shape twice" — is a genuine
   improvement but a separate change.
2. **Fleet visibility.** A rollup across repos ("N awaiting absorption, M resolved this month")
   was raised in the same demo. It belongs to the trend layer, not here, and is listed as a
   non-goal above so it does not get smuggled in.

# `chat-summary` — one rendered block, no prose

**Date:** 2026-08-27
**Status:** design approved, not implemented

## Problem

Running `/drift-detector` in the CLI produces the report, and then five more blocks. A PM ran it,
read the result, and was lost by what followed.

This is specified behaviour, not Claude improvising. `commands/drift-detector.md` §"Deliver the
report" instructs, in order:

1. verify, and name every artifact the run wrote;
2. paste `drift.md` verbatim with a 2-line headline;
3. list every representation as a link;
4. "honesty surfaces" — non-`CURRENT` catalog verdicts, non-`HIGH` coverage grades, `UNKNOWN`
   repos, an `/drift-absorb` offer, and how to mute a finding;
5. offer weekly scheduling — cadence, the exact crontab line, `unschedule`, two log paths, plus a
   "freshness on demand" paragraph;
6. offer to clean up run-output folders.

So the answer arrives first and is followed by five blocks, three of which ask the reader to decide
something. The reader wanted a result and was handed a setup interview.

There is a second, quieter problem. **Every other surface this tool publishes is a verified
projection of `drift.json`** — `drift.md`, `summary.html`, `dashboard.html`, all re-parsed by
`verify` and failed if they disagree. The chat output is the exception: it is prose, written by a
model, different every run and between models, and covered by nothing.

## Goal

The chat deliverable becomes a single block the tool renders, so it is short, honest, identical
every run, and verifiable.

## Non-goals

- **No change to `drift.md`.** It stays the complete, verified report. It becomes a *link* rather
  than the thing pasted, so it stops competing with the summary for attention.
- **No change to what is scanned, found, or concluded.** This is a presentation change only.
- **The AI plane's leads output is not reduced, reordered or folded in.** It prints in full,
  exactly as today. The closing block comes AFTER it and names its result in one line, so a reader
  knows the pass ran — but nothing about the leads themselves changes. They are a different tier,
  explicitly not certified findings, and summarising them into a rendered block would blur the
  distinction the three-plane design exists to keep.
- **No new CLI flags for tuning the block.** One shape, or it is not standardised.

## Design

### 1 · `drift-scan chat-summary --state <dir>`

**This is a CLOSING note, and it is always the last thing emitted** — after the deterministic
report and after the AI plane's leads. That ordering is the fix, and it is a separate point from
brevity: the old output did not end, it trailed off into offers, so a reader could not tell whether
more was coming. A run that visibly finishes is worth as much as a run that reads short.

Emits the closing block to stdout as Markdown. A pure function of `<state>/drift.json`
— every figure it needs is already in the payload:

| Block | Source |
|---|---|
| headline counts | `counts` (`fixes`, `byOwner.*.review`, `reposAffected`, `reposScanned`) |
| delta since last scan | `delta` |
| most urgent sunset | `actions[]`, earliest past-due `date` |
| "Do first" | `actions[]`, top 3 |
| UNAUDITED vendors | `catalog[]`, verdict not `CURRENT` |
| UNKNOWN repos | `shapes[]`, verdict `UNKNOWN` |
| AI pass result | the leads blob written by the AI plane — count only, never content |

Nothing is recomputed and nothing is read from anywhere else, so the block cannot disagree with the
report it summarises.

### 2 · The shape

```
🔴 12 fixes · 🟠 34 to review · across 16 of 18 repos
🆕 3 new · ✅ 1 resolved since 2026-08-20
⏰ Most urgent: eBay Finding API retired 2025-02-05 — 4 call-sites

Do first
  1. …
  2. …
  3. …

What this scan could NOT see
  • 1 vendor UNAUDITED — 0 findings there is not evidence of health
  • 3 repos UNKNOWN — /drift-absorb <folder> teaches the scanner what it missed

AI pass: 7 leads raised (above) — leads, not findings; nothing entered drift.json

Scan complete. Reports: drift.md · summary.html · dashboard.html · drift.json
Weekly scheduling, cleanup and blind-spot absorption are available — just ask.
```

The last two lines are the point of the whole change: **"Scan complete"** tells the reader the run
ended, and the reports line tells them where it landed. The AI line accounts for the pass without
re-stating it — the leads are already above, in full.

Around twenty lines, against five blocks today.

**"What this scan could NOT see" keeps its own heading, always.** It is the product's thesis —
*"0 findings for an UNAUDITED vendor is not evidence of health"* — and the reason the old output
failed is not that it was long but that the honesty was buried in prose among sales offers, where
it read as one more thing to skip. When there is nothing to report the section still renders, with
`• nothing — every vendor CURRENT, every repo read`. An absent section is indistinguishable from a
section nobody wrote.

**The footer is one fixed line.** It never expands into a pitch. Scheduling remains discoverable
without demanding a decision from someone who came to read results.

### 3 · The command file shrinks

`Deliver the report` becomes three steps: **verify → paste `drift.md` and run the AI plane as
today → paste `chat-summary` LAST → stop.**

The contract must be explicit, because the current file's structure is what invited the tail:

> Emit the tool's block exactly. Do not re-summarise it, re-order it, add a headline, append next
> steps, or offer anything. If the user asks about scheduling, cleanup or blind spots, answer then.

Steps 3–6 are absorbed into the block or the footer. The cron mechanics, crontab line, `unschedule`
and log paths move to `/drift-detector help`, where someone who asks will find them.

### 4 · `verify` covers it

A new invariant, alongside `check_md_matches_payload`: re-render the block from the payload and
fail if its figures disagree. The chat output stops being the one surface with no guarantee.

## Testing

Written test-first; each guard proved against its bug.

1. Golden file over a fixture payload — the whole block, so any drift in wording or order is a
   visible diff rather than a judgement call.
2. Every headline figure equals the payload's own counts, asserted against `counts` rather than a
   literal, so a renderer that invents a number fails.
3. The clean-fleet case: `0 fixes`, and "could NOT see" renders its nothing-to-report line rather
   than vanishing.
4. The no-previous-scan case: the delta line says so, and does not render `🆕 0 · ✅ 0` as though a
   comparison happened.
5. `verify` fails a payload whose counts were doctored after rendering.
6. A line-budget test — the block may not exceed 30 lines on a fixture with 50 findings, so it
   cannot quietly regrow into the thing being replaced.

## Risks

| Risk | Mitigation |
|---|---|
| This changes the primary output for every existing user, not just the PM | It is the point; the CHANGELOG says so plainly rather than describing it as a tweak |
| A model ignores "paste exactly" and adds prose anyway | Cannot be enforced in code. The command file states it once, unambiguously, instead of the current six-step structure that invites elaboration |
| Truncating to 3 actions hides work | The count is in the headline and `drift.md` is one link away; three is what fits a glance, and the alternative is the wall being replaced |
| The block and `drift.md` drift apart | Both are projections of one payload, and `verify` now re-parses both |

## Open question, deliberately deferred

Whether the closing block should also render when a scan FAILS — "this is where it ended" is
arguably more valuable on a bad run than a good one, and today a failed scan ends in whatever the
error text happened to be. It needs its own thinking about what an honest failure summary contains,
so it is not bundled here.

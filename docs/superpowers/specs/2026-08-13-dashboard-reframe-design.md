# The dashboard says what it means

**Date:** 2026-08-13
**Status:** approved, not yet implemented
**Origin:** the owner opened the cockpit after a week away and could not remember what the tabs meant
**Advisory:** architecture review by Fable, recorded inline where it shaped a decision

## Why

The scanner is right and the page is not. Three complaints, one diagnosis.

**The AI Frontier plane is always empty**, so it reads as dead weight. The sharper reason, from the
Fable review: *two of its three tiers were never findings.* `research` is coverage-lifecycle
progress — it answers "what happened to my queued vendors", a property of the tracking column.
`shaped` and `leads` are findings with weaker provenance. The AI plane was a column and a badge that
got promoted to a peer of the product. It reads as dead weight because it is misfiled, not because
it is unused.

**The tiles do not sum, and nothing says so.** `Tracked` counts distinct *vendors* (21) while
`Detected`/`Queued`/`Assets` count endpoint *rows* — so 21 + 3 + 43 = 67 against a Detected of 73.
The row count behind Tracked is 27. Two units in one row of tiles, unlabelled. Meanwhile
`counts.coverage` is already a true partition of `detected` and sums correctly; the honest structure
exists in the payload and is not what the page shows.

**Nothing on the page defines its own terms.** "Queued" and "Unaudited" carry the product's entire
honesty argument and appear as bare numbers.

Underneath all three: the owner found an ASCII tree of the same numbers immediately legible where
the tile strip was not.

## What we are building

### 1. Two sections, not three planes

**Vendor Drift is the page** — the default view, owning the timeline, the endpoint inventory and the
coverage lifecycle. **Supply Chain moves down one level** to a secondary section, internally
unchanged; CVE/EOL work is genuinely isolable from vendor drift and has a different owner
(devops vs developer). The shared headline that currently mixes CVE fixes with sunsets splits with it.

**The AI plane is removed as a destination and folded in as provenance:**

| tier | where it goes |
|---|---|
| research verdicts | inline on the queued/tracked lifecycle — a queued vendor shows when it was researched and what was found, with its source |
| shaped call-sites | into the findings table, carrying the existing `GATE-VALIDATED` badge |
| leads | a clearly-marked subsection, `UNVERIFIED LEAD` |

**This is a render-time join keyed on vendor/host, never a payload merge.** `leads-data`,
`adhoc-data` and `research-data` stay separate blobs; `verify.check_ai_firewall` keeps asserting no
AI record reaches the certified payload. Visual merge, data firewall intact.

### 2. The tree is the header, and it is machine-checked

The ASCII breakdown becomes the literal header of the Vendor Drift section, built from
`counts.coverage` — the structure that already sums.

It renders as a real nested `<ul class="tree">` with `data-node`, `data-n` and `data-unit`
attributes, **not** a `<pre>`. That is the point: `verify` parses the DOM source and asserts every
node's children sum to their parent.

This matters more than it reads. Nobody involved in this project can see rendered HTML — not the
owner, not the implementing agent, not the reviewer — and that blind spot has shipped real bugs
twice. A tree whose arithmetic is machine-checked is the first presentation element that can be
*proven* rather than eyeballed. It converts a readability request into a guarantee.

**Honesty rules baked into the structure:**
- A node whose count is unknowable renders `data-n="null"` and the text *"not counted — <reason>"*,
  never `0`. Absent must never render as zero.
- The queued node always carries a research-status suffix: *"3 queued · researched 2026-08-13
  (4 vendors)"* or *"3 queued · research: never run"*. The distinction between "ran and found
  nothing" and "never ran" survives.
- Each node is a click-target that sets the existing row filter. **The tree is the navigation**; the
  mixed tile strip is retired.

### 3. Units become self-evident

Every tree node counts **endpoint rows** (73 = 30 + 43; 30 = 27 + 3). The vendor count survives only
as the annotation the owner found legible: *"27 classified rows → 21 distinct vendors"*.

The tiles that were genuinely findings-shaped move to where they have context: `Sunsets` and
`Past-due` to the timeline header; `Unaudited` and `Private` to the Coverage footer, which is where
"cannot see" content already lives. Every displayed number carries a unit word in its label,
enforced by a verify check that each `data-node` declares a `data-unit`.

### 4. Definitions live under the tree

One `<details class="defs">` — *"What these mean"* — with a `<dt>/<dd>` per node key. A verify
invariant asserts **every `data-node` key in the tree has a matching definition entry**, so the
glossary cannot silently drift from the numbers it explains. Tooltips were rejected: not
discoverable, and not verifiable from source.

### 5. Research runs itself, unprompted

**Decision by the owner, overriding both the Fable recommendation and the implementing agent's:**
the research pass runs automatically on every scan, with **no consent prompt and no cap**.

The tradeoff being accepted, recorded plainly: research costs tokens and hits the network, so every
scan now spends without asking, and a fleet scan spends per repo. Fable's position was that silent
unbounded spend is itself a form of dishonesty and argued for remembered consent plus a per-run cap;
the owner's position is that the tool's job is to deliver the end result without making the user
manage it. The owner's call governs.

Two things soften it without re-litigating it:
- **On-page disclosure.** The queued node states what the last research pass covered and when. This
  is reporting, not a prompt.
- **A config switch** (`research.auto: false`) so a CI operator can turn it off. Default stays
  auto-on, uncapped, as decided.

## Testing

Per CLAUDE.md principle 5, every guard is shown to FAIL on its bug before the fix lands. New
invariants, each with a proving test:

- **tree-sums** — children sum to parent for every `data-n`; fails on a hand-edited node.
- **tree-units** — every `data-node` declares a `data-unit`.
- **tree-definitions** — every node key has a `<dt data-def>` entry.
- **tree-certified-only** — no `data-n` exceeds what `counts` supports, so an AI number can never be
  folded into a tree node. This is the firewall's presentation-layer counterpart.
- Absent-vs-zero: a null-count node renders its reason, not `0`.
- Determinism: identical input renders a byte-identical page.

## Risks

**Provenance flattening is the real firewall risk.** A visual join tempts a future edit to add shaped
counts into tree nodes. The rule is absolute: tree and header numbers derive from `drift-data` only.
`tree-certified-only` is what enforces it mechanically rather than by convention.

**Three existing invariants are coupled to the template's source text** and will trip on
restructuring — by design, since they are substring checks:
- `check_timeline_lanes` greps for `timeline.dated` and `timeline.undated`; both bindings must survive.
- `check_accessor_coverage` constrains loop-variable names (`a`/`e`/`p`/`cv`/`row`) in any new render code.
- The tier legend and footer copy name "the AI Frontier plane" and must be rewritten.

**Deep links.** `?plane=ai` must map to the new location, not fall through to a default view.

**A research "retiring" verdict must never read as a certified sunset** — the badge plus a
"not in catalog yet" suffix is load-bearing, not decoration.

## Out of scope

Even tile alignment — the tile strip is retired, so the problem largely dissolves, and alignment is
not verifiable by anyone on this project. SBOM/SARIF cosmetics and a timeline redesign are deferred.

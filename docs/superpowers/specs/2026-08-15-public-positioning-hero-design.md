# Public positioning hero rewrite — design

Date: 2026-08-15  
Status: approved (approach 1 / scope B)  
Source brief: `docs/PUBLIC-POSITIONING-CLAUDE.md` (unpark in the same change)

## Problem

Public soft-ship was held at ~60% partly because positioning stayed **PARKED**: the GitHub README and marketplace blurb still read as “deterministic scan + AI cross-check / Cockpit / CI” rather than the locked boast frame. Strangers hitting the repo should get a **Claude-plugin-first** 10-second promise without mistaking the scan path for an LLM.

## Goals

1. Lead every stranger-facing surface with *AI proposes. The scanner adjudicates.* under tagline *Know before it breaks.*
2. Make **Claude Code plugin install** the only hero CTA; CI/headless is a footnote.
3. Soft-claim hygiene: never imply the certified scan is model-driven; empty AI Frontier = no pass, not clean; never inflate Frontier counts as certified fixes.
4. Unpark the positioning brief so future work isn’t blocked by a stale PARKED banner.

## Non-goals

- FRONTEND-PLANE / HTML hero / screenshot swaps / Vue restyle
- Promoting `drift-scan` / fleet CI as the homepage story
- Product code, Shopify gap commit, eval batches, version bump (unless asked separately)
- Putting client hosts in public `agent/*.yaml`

## Locked copy frame

| Element | Text / rule |
|--------|-------------|
| Tagline | *Know before it breaks.* (unchanged) |
| Boast | *AI proposes. The scanner adjudicates.* |
| Sub | Claude finds what the scan can’t see yet; Drift Detector proves it (`file:line`, sourced dates) or honest **needs-human** |
| Forbidden | “AI-powered scanner” (or equivalent) as if the scan path is the model |
| Trust | Certified findings vs AI leads stay separate; `verify` remains the only correctness claim |

## Surfaces

| Path | Change |
|------|--------|
| `README.md` | Rewrite hero (logo → tagline → boast → short proof paragraph → three kinds of rot as *certified* catches). Keep install as primary CTA. Collapse “Headless — CI…” to a short footnote under Use it. Soften Cockpit / AI Frontier wording if it over-claims; leave architecture/screenshots otherwise. |
| `.claude-plugin/plugin.json` | Replace `description` with ~1–2 sentences matching the boast frame (deterministic core + Claude proposes / scanner adjudicates). Keep version/keywords unless a keyword implies AI-as-scanner. |
| `.claude-plugin/marketplace.json` | Same `description` as `plugin.json` (versions must stay matched — do not drift them in this change). |
| `docs/PLUGIN.md` | Open with the same frame; install/use steps unchanged in substance. |
| `docs/PUBLIC-POSITIONING-CLAUDE.md` | Remove PARKED banner; mark **ACTIVE** / shipped; keep Do-not list. |
| Orchestrator `deprication-agent/docs/PARKED-public-positioning.md` | Retarget to the active shipping-tree doc or delete/replace with a short “unparked” pointer. |

## README hero outline (target shape)

1. ASCII logo (keep)
2. Tagline blockquote
3. Boast line + one short paragraph (propose / adjudicate / needs-human)
4. Three kinds of rot (sunsets / EOL / CVE) — certified path
5. One sentence: runs as Claude Code plugin; certified scan is zero-token / deterministic
6. `## Use it` — marketplace install + `/drift-detector` (unchanged commands)
7. Footnote: headless/CI one-liner (not a peer section with full exit-code essay — keep exit codes only if one short clause)
8. Rest of README (Architecture onward) largely intact; edit only soft-claim offenders

## Soft-claim checklist (pass before done)

- [ ] No phrase that equates the scan engine with an LLM
- [ ] AI Frontier described as shaped / gate-validated leads, not certified fixes
- [ ] Empty / no-AI run does not read as “all clear” from the AI plane
- [ ] CI is not co-equal with plugin install in the first screen
- [ ] `plugin.json` and `marketplace.json` descriptions identical; versions still match

## Success criteria

- A cold reader of the README first screen understands: Claude plugin → AI proposes → scanner proves or needs-human.
- Marketplace listing description matches that frame in one glance.
- Positioning doc is unparked; orchestrator pointer no longer says “do not start.”
- No product/runtime behavior change; docs-only (plus unpark).

## Implementation note

Docs-only change in shipping tree `/home/tops/Projects/tops/drift/drift-detector-scan` (plus orchestrator pointer). Prefer one focused commit after review; user pushes with their PAT.

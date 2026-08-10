# HANDOVER — the AI-native (triage-first) branch

> **You are the agent picking up the AI-native direction in a fresh window.** Read this whole
> file first, then the plan it points to. A parallel window is working a *different* track (the
> demo "all-integrations" flip) — **do not touch that; it is not on this branch.**

## Where things stand (2026-08-10)

Drift Detector shipped as a deterministic, zero-LLM scanner + Claude Code plugin
(`TOPSinfo/drift-detector-scan`, public, PyPI `drift-detector-scan` 1.2.3). A first-run UX
failure on a real client repo (a real-estate SPA scanned as a built copy → a *wall of
unknowns*) triggered a strategic question: **should this go "all AI"?** The owner asked
Fable 5 (product architect). The answer, adopted:

**Yes — but only as form (A): AI reasons; deterministic tools supply every fact.** The AI
decides *what to look at* and *how to characterize it*; every load-bearing fact (a call-site,
a date, a classification) comes from a **deterministic tool call** and passes the **`absorb`
gate**. The moment the AI asserts a fact a tool didn't produce, we become the hallucinating
scanner our entire pitch is against (CLAUDE.md principle 2). **We are already form (A)** —
CLAUDE.md line 1: "Claude only orchestrates; the heavy work is Python + ast-grep." This
branch makes that AI layer *smarter and more visible*, not a rewrite.

### Delivery model (decided)
Stay a **Claude Code plugin** — the user pays tokens, zero infra, day-one results. A **Claude
Agent SDK app is a *different product*** (your token bill, your hosting) — banked for the later
service/GitLab phase, NOT this branch. Existing Python functions become tools **coarse-grained**
(pipeline *stages*: `scan_repo`, `catalog_lookup`, `absorb_check`, `verify` — never
`classify_url` a thousand times). Cheapest tool seam: the model already calls `./bin/drift-scan`
via Bash — **a CLI is a tool.**

### RAG / multishot verdict
- **Skip vector RAG.** The catalog is small, exact, reviewed YAML; semantic retrieval would
  inject *plausible near-misses* into the one place that must be exact — the exact failure the
  gate exists to refuse. "The catalog **is** retrieval — deterministic, exact-match."
- Real retrieval value = **live WebFetch of vendor changelogs** during refresh (fetch + gate).
- **Multishot** helps in two places only: shape-proposal (few-shot gate-*passing* examples) and
  host-triage stability. Skip self-consistency voting — the gate already *is* the filter.

## What to build (the plan)

**Read:** [docs/superpowers/plans/2026-08-10-host-triage-taxonomy.md](docs/superpowers/plans/2026-08-10-host-triage-taxonomy.md)

That is **Phase 1 (M1)** — the *deterministic floor*. It adds a `hostClass` to every endpoint
(reviewed reputation catalog + URL-shape/call-context heuristics, zero AI) so real API leads
rank above icons/CDNs/analytics, and turns today's *silent* `_IGNORE` drop into *visible,
counted* buckets. 7 bite-sized TDD tasks, each independently shippable; the mls-mapper incident
becomes a regression fixture (Task 7). **Build M1 first** — it fixes the incident deterministically
and produces the small `api-lead` bucket the AI agents will consume.

### Phase 2+ (plan these separately, AFTER M1 lands)
The "triage-first scan" agent topology (Fable's design), all inside the plugin:

```
/drift-detector (orchestrator — the AI)
 ├─ scan_repo       → bin/drift-scan run   (deterministic; facts)
 ├─ catalog_lookup  → exact YAML match      (deterministic; dates+sources only)
 ├─ [subagent] Recon   read-only: characterizes the repo + each api-lead/unknown host
 │                     → verdict + file:line evidence
 ├─ [subagent] Shaper  drafts staged ephemeral-shape YAML, few-shot with gate-passing examples
 ├─ absorb_check    → agent/absorb.py       (THE GATE: refuses unclaimed vendors, refuses any
 │                     date not from catalog, verifies claims against the repo)
 └─ verify          → bin/drift-scan verify  (green verify = the only correctness claim)
```
AI proposes; the gate disposes. Rejected proposals surface as *"AI proposed, gate refused:
<reason>"* — itself a trust artifact. AI-origin entries carry `origin: ai-proposed, gate: passed`
(the per-row origin badges already exist in the cockpit).

## How to execute

Use **superpowers:subagent-driven-development** on the M1 plan: fresh implementer + task reviewer
per task, on THIS branch (`feat/triage-first`, off the canonical clean history). Each task ends
green. Then write the Phase-2 plan (brainstorm → writing-plans) for the Recon/Shaper agents.

## Non-negotiable constraints (from CLAUDE.md — do not break even if tests pass)

1. **"Cannot see" ≠ "clean".** M1 *strengthens* this: nothing is hidden; every host is classed
   and counted. Never silently drop.
2. **Never invent a date.** `hostClass` is orthogonal to `classified`/`vendor`/dates. AI never
   asserts a date; dates come only from the catalog, through the gate.
3. **Deterministic, zero tokens in the scan path.** ast-grep pinned; reputation loaded from disk;
   no fetch at scan time; byte-identical output.
4. **The catalog is data, reviewed.** New entries enter via staging + `drift-scan absorb`.
5. **Prove a guard against its bug.** Reproduce first (the incident fixture must FAIL pre-fix).
6. **`verify` is the only claim of correctness** — you cannot see rendered HTML.
7. Runtime = **stdlib + PyYAML** only. `verify.check_accessor_coverage` reserves cockpit loop
   vars `a|e|p|cv|row` — any new `v-for` must use other names.

## Security (still in effect)
- Two live tokens from earlier this session (a GitHub `ghp_…` and a GitLab bot `glpat-…`) must
  stay **masked** — never echo beyond prefix/length. The owner is rotating them.
- Client identifiers must **never** enter this public tree (they live in the private
  `DRIFT_INTERNAL_IDS` deny-list). See `tests/test_no_internal_identifiers.py`.

## Repo state
- Branch `feat/triage-first` off the canonical clean history (`463f8da`).
- This branch carries: the M1 plan + this handover. No code yet — M1 is unbuilt.
- The parallel "all-integrations demo flip" work is on a **different branch** — ignore it here.

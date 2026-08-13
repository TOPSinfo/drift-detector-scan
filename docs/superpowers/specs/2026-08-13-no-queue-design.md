# No queue: the AI resolves in-run, the deterministic layer still owns the answer

**Date:** 2026-08-13
**Status:** approved, not yet implemented
**Origin:** the owner opened the three-repo summary and found ten hosts sitting in `queued`

## Why

The first multi-repo scan queued ten hosts. Broken down:

```
9  own-infra token guesses      sebagofoods.com, neptunes.sebagofoods.com,
                                sebagodistribution.com, sebagoit.mooo.com,
                                crm.promoteplus.ai, promotepluscdn.com, …
1  genuinely uncatalogued       idximages.directaxess.com
```

**Ninety percent of the queue was the tool hedging on a guess it had already got right.**
`sebagofoods.com` inside the `sebago-foods` repo is not a research question. That hedge was
introduced deliberately — a review found that a repo named after its vendor (`acme-mailgun-sync`)
could swallow that vendor, so token-derived claims were kept queued rather than acted on. Seeing the
real output, the owner judged the trade wrong: nine obviously-owned hosts parked in a backlog is
worse than the risk it insured against.

The owner's framing, which governs this design: **treat the tool as a native AI tool that will
always be used with AI.** A queue is a promise to do work later. There is no later.

## The knot, and the answer

The owner wants the AI to settle coverage state. But `verify.check_ai_firewall` forbids AI-derived
records in the certified payload, and that firewall is the branch's most valuable guarantee. Taken
naively, "the AI marks this host own-infra" writes an AI decision into `drift.json`.

**The resolution is this project's existing `absorb` doctrine, applied to coverage:** the AI never
writes the answer. It writes *evidence*, a gate validates it, the evidence becomes reviewed data,
and the **deterministic scanner re-derives the answer itself**.

```
1  scan (deterministic, zero tokens)        → some hosts unresolved
2  AI resolution pass                       → PROPOSALS + evidence
3  gate                                     → refuses anything unevidenced
4  proposals become reviewed data           → own-domains / vendor entries / sourced sunsets
5  re-scan (deterministic, zero tokens)     → everything classifies deterministically
```

The certified `drift.json` is produced entirely by step 5. No AI record ever enters it, the firewall
holds untouched, and the user sees one command and no queue. Two scan passes cost seconds and zero
tokens, because the scan path is deterministic by construction.

This is the same shape as idiom absorption, which already works this way. The insight is only that
*coverage resolution is an absorption problem*, not a reporting problem.

## What resolves, and how

| unresolved host | AI produces | gate demands | becomes |
|---|---|---|---|
| own-infra candidate | a judgement that the domain belongs to this project | the reason, naming the evidence | an own-domain entry → deterministic `own-infra` |
| unknown third party | the vendor's identity | a fetched page confirming the host is that vendor's | a `vendors.yaml` entry → deterministic `tracked` |
| a vendor with no retirement data | a sourced verdict | **a source URL fetched this session, and the date verbatim in the excerpt** | a sunset entry, or an attestation of `current` |

**The date gate does not move.** Everything else the AI may settle inline; a retirement date it may
only propose, and only with a source. This project has shipped plausible-but-wrong dates before and
the gate is the reason it stopped. "AI-native" is not "AI-trusted".

## What the tree shows

`queued` is removed from the rendered tree. A host that could not be settled shows as:

- **`needs human`** — the AI ran and could not reach a confident verdict
- **`blocked`** — a source could not be fetched

Both are honest *"we tried and failed"* states. The distinction from `queued` is the whole point:
`queued` said "we have not looked yet", and after this there is no such state to be in. An empty
tree now means *resolved*, not *ignored* — which is only true because the pass actually ran.

## Risks

**The own-infra loosening is a real one, and it is the risk the old hedge existed for.** A repo named
after its vendor can still mislead. The mitigation moves from "queue it" to "make the AI justify it":
a claim must carry its reasoning, and a host that matches a **catalogued vendor** may never be
claimed as own infrastructure regardless of what the token says — the deterministic guard already in
`own_infra` stays, and the AI cannot override it.

**Two scan passes must produce the same certified result given the same catalog** — the re-scan is
not permitted to be a different kind of scan. Determinism is asserted, not assumed.

**A failed AI pass must degrade, not block.** If the model is unavailable, the run completes with
hosts in `needs human` and says so. The deterministic report is never withheld waiting on the AI.

## Out of scope

The AI cross-check plane (`leads.json`) is unchanged — it remains unverified leads, separate blob,
separate badge. This design is about resolving *coverage*, not about promoting leads to findings.

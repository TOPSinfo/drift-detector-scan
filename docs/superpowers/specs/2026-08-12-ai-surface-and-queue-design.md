# One AI surface, and a queue that means something

**Date:** 2026-08-12
**Status:** approved, not yet implemented
**Origin:** testing 0.18.0-beta against a Laravel CRM (27 hosts sitting in `queued`, and a second
AI dashboard nobody asked for)

## Why

Two complaints, one root cause each.

**The queue does not mean what it says.** `queued` is documented as "an API service we haven't
researched yet — the research loop's work-list". On a real repo it held 27 hosts, of which **3** were
genuinely un-researched third-party APIs. The rest were documentation and spec sites, social links,
the client's own infrastructure, test-fixture domains, and a dependency's stock config defaults.
`www.rfc-editor.org` sat in the queue while the same host is already excluded as boilerplate
elsewhere. Pointing the research loop at that list would spend tokens researching `soundcloud.com`.
The queue is not a research backlog; it is a classification gap wearing a backlog's name.

**There are three AI surfaces.** `probabilistic.html` (unverified leads), `adhoc.html` (gate-validated
shapes), and the AI Frontier tab already built into `dashboard.html` and fed by `research.json`. The
dashboard tab is the one users actually look at, and it reads 0 because nothing routes into it. The
two side-car HTML files are parallel dashboards that duplicate a surface that already exists.

## What we are building

### Part 1 — the queue becomes a classification fix

The machinery already exists and is correct: `host_class.classify()` resolves an uncatalogued host to
a member of a closed `VOCAB`, backed by `host_reputation.yaml` as reviewed data. The vocabulary
already contains `own-infra`, `social-widget`, `asset-cdn`, `boilerplate` and `vendored-lib`. Nothing
new needs inventing — the hosts are simply falling through to `unclassified`.

**1. Reputation catalog additions.** Generic, widely-seen hosts only:

| hostClass | hosts |
|---|---|
| `boilerplate` | spdx.org, spec.openapis.org, rfc-editor.org, reactjs.org, redux.js.org, vladimirgorej.com |
| `social-widget` | fb.me, snapchat.com, threads.net, soundcloud.com |
| `asset-cdn` | get.adobe.com |

Each entry carries a load-bearing comment saying why, per the catalog-is-reviewed-data principle.
**No client hostname ever enters this file** — it ships in a public repo.

**2. Test and placeholder domains.** `classify_url.py` already drops one class of placeholder host.
Extend it to the reserved names from RFC 2606 / RFC 6761 — `.test`, `.example`, `.invalid`,
`.localhost`, and the `example.{com,net,org}` / `acme.com` conventions — classified `boilerplate`.
This covers `cdn.example.test`.

**3. A new `agent/lib/own_infra.py`.** Client infrastructure cannot be catalogued (privacy) and cannot
be pattern-guessed (a `cdn.*` heuristic would claim a genuine CDN vendor). It must be *derived from
the repo being scanned*. Two signals, both already present in the inventory:

- **Repo-name token.** The repo directory basename and the git remote path give `zenithapp-crm`.
  Split on `-`/`_`, keep tokens of **6 or more characters**, drop a generic stop-list (crm, app, api,
  web, admin, portal, client, server, laravel, symfony, django…). Result: `{zenithapp}`. A host
  containing that token is own-infra. This catches all three of the observed hosts —
  `crm.zenithapp.io`, `zenithappcdn.com`, `qa-zenithapp-idx.devhost.io` — and none of the real
  vendor hosts.
- **Org domain from the git remote.** `https://git.devhost.io/root/zenithapp-crm.git` yields the
  registrable domain `devhost.io`. Hosts under it are the organisation's own infrastructure. This
  catches the third host independently of the name token.

Config-derived inference was evaluated and **rejected**: the target repo's `.env.example` has
`APP_URL=http://localhost` and its `composer.json` name is the framework default `laravel/laravel`,
so neither signal produces anything. The design must not rest on fields real repos leave at default.

`own_infra` is consulted **before** the `api.` host-label rule, so `api.<client>.com` classifies as
own-infra rather than as an API lead. It is never consulted for a **catalogued** (classified) host —
a known vendor always wins, so a client whose name collides with a vendor cannot suppress that vendor.

**4. Ten vendors into `vendors.yaml`.** Three found by the AI cross-check and confirmed in code —
JustCall (`api.justcall.io`), Zapier (`hooks.zapier.com`), Microsoft identity
(`login.microsoftonline.com`) — plus the seven AI providers that a dependency's published config
enumerates: DeepSeek, Groq, Mistral, xAI, OpenRouter, ElevenLabs, VoyageAI. All ten become `tracked`
with a catalog verdict of **UNAUDITED** until somebody attests them. That is the honest state:
detected and classified, retirement list unchecked. It is not a silent promotion to "clean".

**Deliberately left queued:** `listingimages.thirdparty.io` is a real third party the code reaches.
Burying it would be exactly the false-clean this tool exists to refuse.

Expected result on the reference repo: **27 queued → ~1**.

### Part 2 — one AI surface, three blobs

`dashboard.html` already embeds `research.json` as a separate `_blob_script` payload, outside the
certified data. Extend that pattern rather than replace it:

| blob | contents | produced by |
|---|---|---|
| `research.json` | research verdicts; a `retiring` verdict carries source + verbatim date | `research --apply` (existing) |
| `adhoc.json` | gate-validated shape attribution for a repo the scanner cannot read | `adhoc-report` (existing) |
| `leads.json` | raw AI leads; `retired` is the tri-state `yes`/`no`/`unknown`, **never a date** | `leads` (new) |

The AI Frontier tab renders all three, with a **per-row provenance badge** — `GATE-VALIDATED`,
`SOURCED`, `UNVERIFIED LEAD`. One tab, but never one undifferentiated pile: the three tiers carry
genuinely different trust and the UI must say so.

**Removed:** `agent/lib/probabilistic_render.py`, `agent/lib/adhoc_render.py`, the `probabilistic`
subcommand, and both side-car HTML outputs. `adhoc-report` keeps writing `adhoc.json` and stops
writing `adhoc.html`.

**Added:** a `leads` subcommand that validates an AI pass into `leads.json`, enforcing the tri-state
`retired` and rejecting any date in a lead. It replaces `probabilistic` and inherits its refusals
(malformed payload, missing `repo` key, no prior scan).

### Part 3 — `verify` gains a firewall invariant

Today the firewall between certified findings and AI output is *file separation*: AI output lives in a
different HTML file, and `verify` covers only the certified files. Once the AI blobs move into
`dashboard.html`, that structural guarantee disappears and must be replaced by an executable one.

`verify` gains an invariant asserting that **no AI-derived record appears in the certified payload** —
`drift.json`'s `counts`, `findings`, `endpoints` and `catalog` must be unchanged by the presence of any
AI blob. The AI blobs themselves stay outside the equality check; they are not projections of
`drift.json` and cannot be verified against it.

This is the load-bearing part of the change. Without it, "merge the AI tab into the dashboard" is a
quiet weakening of the tool's central claim.

## Testing

Per CLAUDE.md principle 5, every guard is shown to FAIL on the bug it targets before the fix lands:

- One test per new reputation bucket, asserting the host leaves `queued`.
- Placeholder/reserved-TLD classification, including `cdn.example.test`.
- `own_infra` derivation: both signals independently; the ≥6-char token rule; the generic stop-list;
  and the negative case — a catalogued vendor is never reclassified as own-infra.
- The `verify` firewall invariant, proven by injecting an AI record into the certified payload and
  confirming `verify` fails.
- `leads` rejects a lead carrying a date, and rejects a non-tri-state `retired`.
- Determinism: two runs over the same inputs produce byte-identical `drift.json` and `dashboard.html`.
  `own_infra` takes repo signals as inputs — no wall clock, no network, consistent with principle 3.

## Risks

**Misclassification suppresses a real vendor.** The precedence change means own-infra is consulted
before the `api.` label rule. Mitigated by never applying it to a catalogued host and by the ≥6-char
token minimum. A short or generic client name simply yields no token, and those hosts stay queued —
failing toward *shown*, which is the correct direction.

**Suppression must never be silent.** Hosts moved out of `queued` remain fully visible under Detected
and Assets. The queue count shrinks because the hosts are correctly typed, not because they were
hidden. "Cannot see" is still never "clean".

## Out of scope

Google APIs and Amazon AWS stay UNAUDITED — the mega-vendor per-product split is separate, already
tracked work. No change to the absorb gate, the sunset catalog format, or the deterministic scan path.

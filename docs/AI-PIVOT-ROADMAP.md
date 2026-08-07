# AI-driven pivot — roadmap & parked work

Decision record for the 2026-08-06 pivot (Fable-5 reviewed, two passes). **Shipped today** in
`0.14.0-beta`: the Claude plugin restored + rewired to the PyPI package via `uvx`, a persistent
`~/.drift/catalog` (learned catalog survives upgrades), and the two-tier flow (certified findings +
a *separate* AI cross-check). The `absorb`-writes-to-site-packages bug is fixed. Everything below is
**deliberately deferred**, ordered by leverage.

## The reframe (why the order below)
The deterministic tool is the **aid**, not the product. Two assets with opposite economics were
being conflated: **idiom shapes saturate** (4 families, ~a closed set of SDK URL-assembly patterns —
enumerable by a maintainer in a week, no crowd needed) while **vendor sunsets compound forever**
(unbounded, perishable, genuinely missing — there is no OSV for "vendor X retires operation Y on
date Z"). OSV/endoflife.date are **not** user-crowd-sourced; they aggregate authoritative vendor
pages — which `catalog_check.py` + `version_lifecycle.py` already do. **So: publish the data before
soliciting it.** The product story is *a deprecation-intelligence feed, with the scanner + plugin as
its delivery vehicle and contribution funnel* (feed free, fleet-scale delivery paid).

## Parked work, ranked by leverage

1. **Publish the sunset feed** (~1–2d, highest value/effort). Cut a public `drift-catalog` repo
   holding `vendor_sunsets.yaml` + `catalog_attestations.yaml` at a **pinned tag**; make the tool a
   client of that tag exactly as it is OSV's. Add **`catalogVersion` to `drift.json`** + a `verify`
   invariant (reproducibility). Establishes maintainer-of-record with zero contributors.

2. **The structural firewall** (1–2d, do *before* the two tiers share one page). A
   `drift-leads/v1` schema where a **date is unrepresentable** (`additionalProperties:false`, no
   `date` field), hash-bound to the scan (`meta.driftJsonSha256`), reject-on-load for date-shaped
   strings. Then 4 new `verify` invariants — no dates in leads, hash-bound, counts unchanged with
   leads present/absent, every rendered lead badged — **each proven to FAIL on a seeded bug**
   (principle 5). **A lead must NEVER enter `drift.json`** (or a green `verify` starts lying).

3. **The integrated single-page two-tier dashboard** (2–4d). `leads-data` as a fourth
   `_blob_script` (leaving `check_blob_matches_payload` byte-identical), a **`Leads (AI · unverified)`**
   peer sub-tab in the probabilistic blue, counts untouched. Today ships as two separate views
   (`dashboard.html` + `probabilistic.html`) — a *stronger* separation; the merged page is polish.

4. **Fix "beyond PHP" deterministically** (ongoing, code — no crowd can do this). New egress idiom
   **families** for JS/TS (`axios.create({baseURL})`, `` fetch(`${base}/x`) `` template literals) and
   Python (`requests`/`httpx` session base) — none fit the 4 PHP-shaped families. Plus more **encoded
   vendor rules** (the Shopify `version_lifecycle` pattern: one rule dates every version forever and
   can't go stale). One encoded rule beats fifty crowd-sourced entries.

5. **Measure the funnel before building the network.** `absorptions.yaml` already logs every
   absorption with its attributed-call delta. Report **lead→absorb conversion rate**. Near-zero for a
   few weeks ⇒ the federated catalog has no fuel and item 6 should not be built.

6. **Federated contribution — only after 5 proves out.** A one-way `drift-scan contribute` that emits
   a **PR** (never an auto-POST); shareability decided by family (`url-assembly`/`url-append`/
   `operation-marker` public; `path-constant` structurally local — `repo`-scoped); replace `evidence`
   (a client `file:line`) with a public **`corroboration` URL** (requiring one *is* the public/private
   classifier). Merge gate: **`drift-eval` recall-non-regression over the pinned corpus** for idioms
   (the one property the local absorb gate structurally cannot test); **source-fetch + the date-string
   found in the document + 2 human approvals** for dated sunsets, forever. Deny-by-default, human
   opt-in.

## Shelved (enterprise lane — do NOT delete, stop investing)
Private GitLab runner, fleet CI templates, the whole delivery layer (issue-filing — a solo plugin
user has no fleet), and the fresh public-repo cutover (now *actively harmful* — this repo IS the
marketplace source and holds the PyPI Trusted-Publisher binding).

## Run-analysis findings (2026-08-06, two real plugin runs, 1.12M AI-plane tokens over 18 repos)

Validated: the tri-state `retired` contract held across **664 records, zero date leakage**;
`toolOnly` was **0** (the rules have no false-negatives vs a reading agent); `verify` was sound.
Issues found, ranked; **A and D fixed** (commit follows this note):

- **A — CRITICAL ✅ fixed.** A degraded run (endoflife.date unreachable) still rendered EOL rows and
  `verify` passed green — indistinguishable from a clean run. Now the `run` banner prints a loud
  `⚠ DEGRADED` line whenever any OSV/EOL source check failed, on *every* run (not just the CI gate).
  *Still TODO (deeper):* per-finding provenance (`sourceStatus: live|cached|skipped`) + a marker in
  drift.md/dashboard + a `verify` source-freshness assertion.
- **D — HIGH ✅ fixed.** The run banner showed raw per-finding audit tallies (29/34) contradicting
  the canonical `drift.json` counts (14/2). Banner now prints the canonical `counts.fixes/review`;
  the CI gate still fires on the raw signal.
- **C — HIGH (TODO).** `ai_results.json` is hand-assembled by the orchestrator (~45–65k output
  tokens of transcription/run). Add `drift-scan ai-collect --state D --in-dir D/ai-parts/` that
  merges per-repo JSON files + validates the tri-state contract. Cheapest big win.
- **B — HIGH (TODO).** No AI-result caching by `head_sha` — re-scans unchanged repos (~35% waste on
  re-runs). Cache `ai_results` per `(repo_path, head_sha)`; `--ai-refresh` to force.
- **H — HIGH (TODO).** The auto AI plane has no cap/budget/size-heuristic — 18 repos = ~731k tokens,
  and the 5 SP-API SDK repos cost 347k for near-useless infra leads. Add `--ai-max-agents` /
  `--ai-budget-tokens` (log what's dropped), skip HIGH+CURRENT repos, and have `plan` print the
  projected agent count + token estimate *before* approval (pairs with the automatic-plane change).
- **G — MEDIUM (TODO, = the parked "beyond PHP" families).** 8 repos PARTIAL from ~5 recurring
  codegen shapes (UriResolver host+version+resource assembly; `$endPoints[...]` tables; Saloon
  `resolveEndpoint`; Laravel `getBranchUrl`; magic `__call` dispatch). Built-in idioms move 8 repos
  PARTIAL→HIGH — higher leverage than per-repo absorb.
- **E — MEDIUM (TODO).** `probabilistic.compare.norm()` collapses `Amazon MWS/Checkout/PA-API/SP-API`
  → `amazon`, hiding genuine `retired:yes` leads. Keep `norm()` for set-maths; dedupe the *actionable*
  `aiOnly` list on `(norm, host, endpoint)` and prefer `retired:yes` when collapsing.
- **F — MEDIUM (TODO).** No duplicate-codebase detection: a repo and a fleet-mirror copy of the same
  code (two paths, identical trees) produced identical findings and double-counted ~¼ of the
  headline. Fingerprint attributed endpoints; emit `duplicate-of`.
- **I/J — LOW (TODO).** Unknown subcommand falls through to `inventory-scan`; no `--version`;
  `doctor` absent from the published package + false-alarms on system python 3.10 (uv provisions its
  own); empty `First call-site` column on package/EOL rows; inconsistent repo naming across artifacts
  (`owner/name` vs tree path); `counts.unknown`/`private` unexplained; output size grows ~0.5 MB/repo
  (a 100-repo fleet ≈ 8–11 MB HTML, past the 16 MB Artifact ceiling).

*The report's own verdict: "if only two things ship, A and D" — both cases where the tool told the
user something more confident than the evidence supported. Those two are now fixed.*

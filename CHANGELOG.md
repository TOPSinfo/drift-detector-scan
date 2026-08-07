# Changelog

All notable changes to the Drift Detector plugin. Dates are YYYY-MM-DD.

## v0.13.0-beta — 2026-07-21

**See what's already broken — and a charts view.**

### Added

- **"Past-due" tile + report row.** A vendor API that is *already retired* (past its
  removal date) is a different, more urgent thing than a CVE fix or an upcoming deadline —
  an integration broken *now*. It gets its own count (`counts.pastDue`), a **Past-due** tile
  in the dashboard's Integrations group, and an "— of which already retired (past-due)" row
  in the Markdown summary. `verify` guards the new number against drift on every surface.
- **A "Most urgent" callout** at the top of `drift.md`, naming the single most pressing
  surface (the most-overdue retired sunset, else the soonest deadline) so the reader has one
  thing to do first.
- **`chart.html` — an online charts view.** The same report data drawn as a risk doughnut,
  a per-vendor retired-vs-upcoming bar, and a most-overdue-first retirement schedule. It
  loads Chart.js from a CDN, so it **needs internet**; if the CDN is unreachable it says so
  and points back at the dashboard. `dashboard.html` stays self-contained and offline — the
  charts view is a separate, additional file. It embeds the same verified payload, so
  `verify` proves the charts draw from `drift.json` and nothing else.

## v0.12.1-beta — 2026-07-21

### Fixed

- **Corrected the plugin's authorship** — author and marketplace owner are now Laxit Patel
  (the creator), and the LICENSE copyright matches. No functional change.

## v0.12.0-beta — 2026-07-21

**Scan a whole client fleet from one URL — and a build you can reproduce.**

### Added

- **Scan a whole GitLab group or user namespace.** Point at `https://git.example.com/acme`
  and the tool enumerates every repo the token can access under it — group *or* user
  namespace — clones each, and scans the fleet. You cannot miss a repo you didn't list. It
  enumerates via `membership=true` (so group-inherited, user-owned, and direct-member repos
  all appear), a URL that is itself a project clones directly, and a mid-enumeration failure
  aborts rather than silently scanning a subset. The plan/approve step previews the whole
  fleet before any scan runs.

### Changed / reproducibility

- **The ast-grep engine is now pinned** (0.44.1; override via `$DRIFT_AST_GREP_VERSION`).
  Previously it fetched "latest", so two machines could get different engines and silently
  different output — at odds with the tool's deterministic guarantee. First run on an
  existing install re-fetches the pinned engine.
- **Rule metadata now travels with each match** (`--include-metadata`), so a scan no longer
  re-reads the rule file — one fewer failure point, same result.
- **`verify` gained a number-format check** — every number in `drift.json` must serialize
  identically across environments (no exponent, ≤1 decimal), guarding byte-identical output.

### Packaging & metadata

- **Fixed the marketplace listing** — it advertised the wrong engine ("Opengrep") and a
  stale version. Now correct and synced to `plugin.json`.
- Added `LICENSE` (MIT), and `homepage`/`repository`/`license`/`displayName` to the manifest.
- Removed leftover build cruft and internal planning docs from the package.
- The plugin now carries its collection identity: **Ashen Oracle** — *Know before it breaks.*

## v0.11.2-beta — 2026-07-21

### Fixed

- **Advice now reads correctly against today's date.** The report used to say "plan
  migration before 2025-01-21" for a date already long past. A retirement whose date has
  gone now reads *"migrate off this API NOW — already retired 2025-01-21"*; only a future
  retirement shows as a *"before <date>"* deadline. The finding's status was already
  date-aware (past = red/action-required, future = amber/review); this brings the wording
  in line.

## v0.11.1-beta — 2026-07-21

### Fixed

- **A scan across repos that vendor the same SDK no longer fails verification.** When the
  same finding (a shared vendor SDK, a common runtime) appeared in two repos with an
  identical repo-relative call-site, the Markdown report rendered byte-identical rows and
  `drift-scan verify` rejected it. The findings tables now lead with a **Repo** column, so
  each repo's exposure is its own row — the disambiguator, and the thing you most want to
  know (which of my repos does this hit). Presentation only; finding totals unchanged, and
  the dashboard already showed the repo.

## v0.11.0-beta — 2026-07-21

**Fix: the plugin could silently run a stale cached build.**

When `CLAUDE_PLUGIN_ROOT` was unset (ad-hoc shells, and especially **scheduled cron
runs**), the runner locator fell back to `find … | head -1` — which picks a build by
directory order, not version, and could grab an OLD cached copy. Symptom: a new
subcommand failing with an argparse error, because an older scanner was executing.

### Fixed

- **Version-aware runner location.** The command files now consult
  `installed_plugins.json` (authoritative) first, then fall back to the newest cached
  build by **semver** (`sort -V`, never `head -1` — lexically `0.10.0-beta` sorts before
  `0.4.0-beta`). Applied to both `/drift-detector` and `/drift-deepen`.
- **Scheduled runs follow upgrades.** The cron wrapper used to pin the runner path at
  install time, so a job kept executing the version that was current when it was
  scheduled — even after upgrading. It now resolves the installed runner at run time.
  **If you have an existing schedule, re-run `/drift-detector schedule <folder>` once** to
  regenerate the wrapper with the fix.
- **Self-check.** The runner warns (never fatal) when a cached build runs while a newer
  one is installed — a stale build no longer executes completely silently.

### Note

Superseded cache directories are the plugin host's to garbage-collect; the version-aware
locator makes any leftover stale build inert rather than a decoy.

## v0.10.0-beta — 2026-07-21

**Two more vendors, a picture of your exposure, and a guided flow that plans before it
scans.**

### Added

- **Shopify** — the first vendor whose retirement dates are **computed, not curated**.
  Shopify versions by calendar quarter (`2024-01`) and publishes a rule (a version is
  accessible for 12 months + 15 days from release), so every version dates itself with no
  per-version catalog entry, and the coverage can't go stale. The rule is verified against
  all seven rows of Shopify's own published support table. Carries Shopify's twist: a
  retired version isn't a 4xx — Shopify silently serves the oldest version, so a stale pin
  is invisible drift.
- **Walmart Marketplace** — 6 sourced sunsets from the vendor's deprecation guide (two
  already retired). Adding it fixed a real detection gap: Walmart front-loads the version
  (`/v3/insights/refunds`), which used to collapse every Walmart call into one `/v3`
  record. Sub-APIs are now scoped apart — the same granularity Amazon already had.
- **Exposure graph** — a Mermaid flowchart in `drift.md`: each repo → the retiring API
  surfaces it calls, red for already-removed, amber for deadline-ahead. Renders natively
  in a Claude artifact, VS Code, and GitHub. A complement to the findings table (every
  node is also a row), with a structural check so a broken graph fails `verify` rather
  than rendering a silent error box.
- **`drift-scan plan`** — resolves and classifies every source (git repo / plain folder /
  cloned / error) **without scanning**, so a run can be previewed and approved first.

### Changed

- **`/drift-detector` is now a guided flow**: an intake menu when no source is given, a
  plan you approve before any scanning, and a delivery that renders the report inline and
  links every representation (Markdown, Dashboard, Data, and the Artifact if you opt in).
  No more per-run "want the dashboard?" question.

### Vendor coverage

Four vendors fully audited, each from a different source shape: Amazon SP-API (page +
OpenAPI specs), eBay (structured RSS feed), Shopify (computed rule), Walmart (deprecation
guide).

## v0.9.0-beta — 2026-07-21

**One canonical report, three views that cannot disagree — and a report you can read
in the chat, not just open in a browser.**

### Added

- **`drift.json`** — the canonical, machine-readable report, now with a published contract
  at `docs/schema/drift-v1.schema.json` and a `schemaVersion` field. This is the spec;
  everything else is a view of it. (Renamed from the internal `dashboard.json`.)
- **`drift.md`** — the report as Markdown: the alarm headline, a summary table, per-family
  findings with dates and call-sites, and both coverage verdicts. It renders in any
  Markdown surface — a terminal, VS Code, GitHub, or **inline in a Claude chat** — so the
  report no longer requires opening an HTML file. Because its source is plain text, it is
  also the view an agent can actually read and check, which the HTML never was.
- **`drift-scan verify` now certifies all three agree.** A green line means `drift.md`,
  `dashboard.html` and `drift.json` are the same data — the claim anyone (or any agent)
  is allowed to make about the report. It re-parses `drift.md`'s tables (splitting on
  unescaped pipes) and fails on a column that an unescaped `|` would truncate on GitHub,
  a summary number that disagrees with the data, or two findings rows that render
  identically.
- Findings now show **call-sites** (located files) rather than a match count, and each
  carries its own **retirement/EOL date** column.

### Changed

- `dashboard.html` is now one viewer among several rather than the report itself. It is
  unchanged in content and still self-contained; `drift.md` is the primary view.
- `/drift-detector` verifies before reporting, reports from `drift.md` (not by eyeballing
  the HTML), surfaces per-vendor catalog verdicts, and can publish the report in-chat.

### Upgrading

- The state directory now also contains `drift.json` and `drift.md`. Anything that read
  `dashboard.json` should read `drift.json` (identical content, canonical name).
- No cache-schema change.

## v0.8.0-beta — 2026-07-21

**Point it at anything — a checkout, a folder, or a URL — and a scan of nothing can
no longer look like a clean bill.**

### Fixed (the one that mattered)

- **Scanning zero repositories is now an error, not a green checkmark.** Pointing the
  tool at a folder with no `.git` — a client's zipped source, a wrong path, a URL —
  used to report `🔴 0 action-required` at exit 0. It scanned nothing and declared
  victory. Now it exits 4 and says *why*: *"has source files but no .git — git init it,
  or clone the repo"*, *"looks like a URL — clone it first"*, *"does not exist"*. This
  is the failure a scan of real Amazon SP-API code hit: the folder had no `.git`, so
  nothing was read, and the report said clean.

### Added

- **Scan a checkout, a plain folder, or a git/GitLab URL — one or many, mixed.**
  - a **plain folder** (no `.git`) is now scanned as one project; the report notes it
    has no history, so "changed since last scan" and clickable `file:line` are
    unavailable for it — clone the repo to get both.
  - a **git/GitLab URL** is cloned into `<state>/sources/` and scanned. Private-repo
    auth reuses your machine's own git setup — if `git clone <url>` works in your
    terminal, it works here. A `GITLAB_TOKEN` in the environment is honoured via a
    transient credential that is **never** written to `.git/config` or the tool's state.
  - a **bad root among good ones** is reported and skipped, not silently dropped.

### Upgrading

- No cache-schema change; existing scans are unaffected.
- A run that resolves to zero projects now exits **4** (couldn't verify) instead of 0.
  If a CI job was passing by scanning nothing, it will now correctly fail — that was a
  false pass.

## v0.7.0-beta — 2026-07-20

**The tool now reports what it has not been taught, and can see seven more languages.**

### Added

- **Catalog coverage per vendor — `CURRENT` / `STALE` / `UNAUDITED`.** Until now a vendor
  with hundreds of call-sites and an empty catalog rendered exactly like a vendor that
  was genuinely clean; that is how eight already-past Amazon retirements stayed invisible.
  The unit is an **attestation** — "somebody opened this vendor's deprecation page on this
  date" — deliberately *not* an entry count, which is gameable by one junk entry and
  unknowable from the inside. New "Vendors unaudited" tile and panel.
  - Consequence, by design: **eBay reads UNAUDITED despite having 12 catalog entries**,
    because nobody has reconciled eBay's own page. Amazon SP-API reads CURRENT
    (checked 2026-07-20). This grades our coverage honestly rather than flatteringly.
- **Egress detection for all 8 languages.** JavaScript, TypeScript, Python, Go, Java, C#
  and Ruby now have HTTP sink rules; previously only PHP did, so every other language
  reported `UNKNOWN / no-egress-signal` and could never be scanned with confidence.
  Every pattern was verified against a real fixture in that language *before* shipping,
  and those fixtures are committed as tests that run the real ruleset through the real
  engine — because a sink rule that matches nothing is worse than no rule: it reports
  coverage the scanner does not have.

### Upgrading

- **Caches invalidate once** (schema 5 → 6) because the ruleset changed; the first scan
  after upgrading re-reads every repo.
- **Expect a new UNAUDITED count.** It is not new risk — it is risk that was always
  there and previously rendered as clean.
- Repos in the seven newly-covered languages may move from `UNKNOWN` to `KNOWN`.

### Known gaps (unchanged, stated plainly)

- Five eBay operations visible on the vendor's deprecation page are **still missing**
  (`getProductCompatibilities`, `updatePaymentInfo`, Return Management, Business Policies,
  Media API). `developer.ebay.com` could not be fetched, and the reachable secondary
  sources disagreed on dates, so **no entry was written** — an unsourced date is the one
  thing this catalog refuses. eBay's UNAUDITED status reflects exactly this.
- Sink→endpoint linking still needs dataflow and remains out of scope; unresolved sinks
  do not affect a verdict when calls are otherwise attributed.

## v0.6.0-beta — 2026-07-20

**Amazon SP-API is now audited, and the report is now checkable by machine.**
v0.5.0-beta reported zero sunsets for a repo with 272 Amazon call-sites. That read as
"clean" and meant "we never loaded Amazon's list". Both halves of this release come
from that: the data that was missing, and the reason nobody noticed.

### Added

- **8 Amazon SP-API retirements**, fetched from the vendor's own deprecation schedule.
  On a real SP-API client, **six of the eight have already passed** — including
  `/fba/inbound/v0` (removed 2025-01-21) with 34 call-sites, plus
  `/reports/2020-09-04` and `/feeds/2020-09-04` (both removed 2024-06-27).
  `/orders/v0` (2027-03-27) and `/finances/v0` (2027-08-27) carry live deadlines.
- **The API-family axis.** Amazon retires per *(family, version)*, not per version:
  four different APIs share the string `v0` with four different fates. Endpoints now
  carry `apiPath` (`/products/fees/v0`), catalog entries can scope on `path:`, and the
  join precedence is operation > path > domain > version. Without this a `version: v0`
  entry would have dated 78 call-sites identically and invented most of them.
- **`drift-scan verify --state <dir>`** — mechanical invariants over the report: every
  tile equals the rows its filter yields, the sunset count is re-derived independently
  from findings, no two rows render an identical label, every action field is projected
  or explicitly declared dropped, and the page's embedded data matches `dashboard.json`.
  Exit 0 clean / 3 violations / 4 nothing to verify.
- **`dashboard.json`** — the payload the page embeds, written to disk. One object, two
  sinks, so what a test asserts on is what a reader sees.

### Fixed

- **Sunset actions collapsed by vendor.** Twelve dead eBay operations with eight
  distinct dates rendered as ONE row and a tile reading `Sunsets 1`; the row also kept
  only the highest-ranked recommendation, silently discarding the rest. Sunsets now key
  on the thing being retired, and rows are labelled with it (`eBay GetCategoryFeatures`).
- **A silently dropped catalog.** `load_sunsets` filtered on `version|domain|operation`,
  so every `path`-scoped entry was read, discarded without a word, and the audit still
  reported clean. An unscopeable entry now raises instead of vanishing.
- **The absorb gate rejected legitimate undated deprecations**, which the catalog format
  explicitly permits. It now accepts them with an explicit `status: deprecated-no-date`,
  so "the vendor set no date" and "I could not find the date" stay distinguishable.
- The dashboard header read `1 repos` on a two-repo scan; it now reads
  `1 of 2 repos affected`.

### Upgrading

- **Caches invalidate once** (schema 4 → 5, endpoints gained `apiPath`). The first scan
  after upgrading re-reads every repo. Old `repos_v4/` directories are inert.
- **A hand-edited `vendor_sunsets.yaml` with a scopeless entry now errors** instead of
  being skipped. That is deliberate — give the entry a `version`, `domain`, `operation`
  or `path`.
- Expect **more findings, not fewer**, on repos using Amazon SP-API.

## v0.5.0-beta — 2026-07-20

**The release that answers the demo.** The PM asked why the scan "skipped"
`getCategoryFeatures`. The answer was structural: our detection unit was the *host*,
and eBay retires *operations* — one host, one path, ~19 calls on independent
lifecycles. There was no way to express "GetCategories is dead, GetItem is alive."
This release adds that axis, and then makes the tool say plainly where it still
cannot see.

### ⚠️ Breaking — read before upgrading

- **Reports are now ONE file: `dashboard.html`.** `AUDIT.md`, `INVENTORY.md`,
  `DRIFT.md`, `bom.json` (CycloneDX) and `findings.sarif` are **no longer written**.
  The drift delta and the ranked fix queue those carried now live *in* the dashboard.
  If you had a bookmark or a pipeline reading one of those files, it will find nothing.
- **Removed surfaces:** the MCP server (`bin/drift-mcp`), the GitLab sync connector,
  and the GitHub Action (`action.yml`). **CI still works** — `bin/drift-scan run
  --fail-on-deprecated` and its exit codes (0 ok / 2 error / 3 gate-tripped /
  4 couldn't-verify) are unchanged and are the interface for any runner.
- **Engine swapped: semgrep/Opengrep → ast-grep**, a static binary the runner fetches
  automatically on first scan. No action needed; a leftover semgrep in an old venv is
  ignored, not used. Scans get substantially faster.
- **Caches invalidate on upgrade** (schema 3 → 4), so the first scan after upgrading
  re-reads every repo. Old `repos_v3/` directories are inert and can be deleted.

### Added

- **The operation axis.** Endpoints carry `operation`, sunsets can be scoped to one,
  and the audit join is operation > domain > version. This is what makes
  `GetCategoryFeatures` (decommissioned 2026-06-04) reportable at its exact
  `file:line` while `GetItem` on the same host stays quiet.
- **Coverage verdicts — KNOWN / UNKNOWN with reasons.** Derived from what the ruleset
  can actually see per language. A Go-only repo can no longer report a confident
  grade off zero signal; it reports `UNKNOWN (no-egress-signal)` and routes to a
  manual pass. **This will look like a regression and is not** — it is the tool
  admitting a blindness it previously hid.
- **Residue** — versioned paths and egress calls we matched but could not attribute,
  listed with `file:line`. The scanner's own conscience; it is what a scout pass reads.
- **`observed` vs `inferred` attribution.** When only one vendor is present, a bare
  path is attributed to it — a guess about the *repo*, not evidence from the *line*.
  That is now labelled. Worth knowing: `amazonspapi` is 2 observed / 18 inferred.
- **`/drift-deepen <folder>`** — the scout. Investigates only what the scan admits it
  cannot read, and must pass a deterministic gate (`drift-scan absorb`) that re-scans
  and rejects any proposal that does not hold up. Dates without a fetched source are
  refused outright.
- **`drift-scan recommend`** — per-repo scan profile (auto / hybrid / manual) with a
  one-line why.
- **10 dated, sourced vendor sunsets** — 6 eBay Trading operations plus the LMS
  retirements, each deep-linked to the release note that announced it.

### Fixed

- Seven bugs from a deliberate adversarial self-audit — malformed engine output
  reading as a clean scan; heredoc URLs lost; orphan operation markers dropped;
  an unreadable repo reporting KNOWN; the absorb gate passing an over-attributing
  proposal; attestations bleeding between same-named repos; a grade that could read
  HIGH beside a verdict of UNKNOWN. Every one was reproduced before it was fixed.

## v0.4.0-beta — 2026-07-17

A measurement instrument for the scanner: run it against real code and see what it catches.

### Added
- **Evaluation / regression harness** (`bin/drift-eval`, contributor tool — see
  [docs/EVAL.md](docs/EVAL.md)). Clones a **pinned** corpus of real public repos grouped by the
  integration they use (`eval/corpus.yaml`), scans them, and scores the scanner: **recall is a
  hard gate** (a repo in `sandbox/ebay/` must detect eBay), plus informational
  noise / version / sunset metrics. Every miss is tagged by a failure-mode enum so the scorecard
  doubles as an improvement backlog. Deterministic, zero-LLM; clones and run artifacts live under
  `~/.drift/` and `~/Projects/sandbox/`, never committed.
- **Corpus:** eBay (5 repos), Amazon SP-API (5), Walmart (4) — all real, SHA-pinned. First scores:
  eBay 5/5 recall + the `svcs.ebay.com` Finding-API sunset fired on a real legacy repo; SP-API 5/5;
  Walmart 4/4.
- **`~/.drift/` home** for eval + central/demo run artifacts (honors `$DRIFT_HOME`). The plugin's
  in-place `<folder>/.drift-detector/` behavior is unchanged.

### Fixed / changed
- **Honest version-rate metric.** Version-extraction rate is now measured only over endpoints whose
  URL actually carries a version, with a separate "no URL version" count — so the scanner isn't
  scored down for APIs that have no URL version (a vendor's design choice, not a scanner failure).

### Notes
- The harness quantified a real boundary: a scanner miss where the API version lives only in SDK
  code (a class constant assembled at runtime) is deterministically unreachable — it marks where a
  future cognition layer would earn its place, rather than something to chase with AST rules.

## v0.3.0-beta — 2026-07-16

The report you actually act on, plus a visual surface and sharper detection.

### Added
- **Ranked fix actions.** Findings now roll up into `(repo, package)` **actions** — 30 CVEs
  against one package are one job (*upgrade `torch` to `2.10.0`*), not 30 rows. `AUDIT.md`
  opens with **"Do this first"** (ranked by severity, then blast radius, each with the exact
  upgrade command), then the full fix queue, then per-repo.
- **Interactive dashboard.** Every scan writes a self-contained **`dashboard.html`** — inline
  CSS + JS, no server, no CDN, opens from `file://`. Clickable tiles (Critical · Fixes · EOL ·
  Sunsets · APIs used · Unknown hosts) over a drill-down fix queue; dark/light theme. Also
  available on demand via `audit --out-html <path>`.
- **Domain-scoped vendor sunsets.** Catalog entries can target a specific host, so a dead
  legacy API is flagged without false-flagging a live one that shares its version string.
  Ships the real **eBay Finding API** (`svcs.ebay.com`) and **Shopping API**
  (`open.api.ebay.com`) retirements (decommissioned 2025-02-05 → migrate to Browse API).
- **Read-only GitLab connector** (`gitlab-sync`). Clone/pull your GitLab fleet with a
  read-only PAT (`read_api` + `read_repository`) into a folder, then scan it — so private
  and in-house wrapper repos get covered. The token is env-only and stripped from every
  repo's `.git/config`. See [docs/GITLAB.md](docs/GITLAB.md). (No GitLab MCP required.)
- **Coverage honesty + `doctor`.** The scan now reports what it *couldn't* see — private/
  unresolvable package sources, unknown external hosts, floor-only vs lockfile-exact versions
  — and `drift-detector doctor <folder>` runs a scan-readiness preflight.
- **Discover-then-classify detection.** Inverted the old allow-list: one broad URL rule
  catches every outbound endpoint, then classifies against a ~40-vendor catalog (now
  including Amazon AWS). Unknown external hosts are surfaced instead of silently dropped.

### Fixed
- **Report ranking bug.** "Most urgent" took the first 15 findings unsorted, burying every
  CRITICAL (including remote-code-execution advisories) under "…and N more". Now genuinely
  ranked.
- **Git-SHA fix versions.** OSV returns some `fixed` values as commit hashes; the version
  sort ranked those above real versions and recommended a git SHA. Now filtered to real
  version strings.
- **Dashboard XSS hardening.** Scan-derived strings are escaped on both surfaces
  (HTML text + the embedded JSON blob), attribute contexts get quote-safe escaping, and
  source links are restricted to `http(s)` schemes.
- **Substring host mis-attribution** (`ups.com` matching `startups.com`) — matching is now
  registrable-domain / boundary-anchored.
- **Stale scan cache** silently omitted new fields; the per-repo cache is now schema-versioned.

### Notes
- The dashboard shows the latest run; week-over-week movement comes from the finding delta,
  not a multi-run archive (a future layer).
- The Google Chat webhook and any GitLab token are **per-install** configuration held by each
  user, never committed. Teammates who install the plugin get their own notifications and
  point at their own repos.

## v0.2.0-beta — 2026-07-15

- Lockfile-exact versions + finding lifecycle (fingerprints, `first_seen`, baseline mute,
  delta-first digest).
- Curated vendor-API-sunset catalog joined against the endpoint inventory.
- Read-only MCP facade (`bin/drift-mcp`) for generation-time prevention from any assistant.
- Deterministic CI: `run --fail-on-deprecated` + composite GitHub Action + SARIF upload.

## v0.1.0-beta — 2026-07-14

- Initial public beta: code-level integration inventory (Opengrep), drift vs last scan,
  OSV + endoflife.date audit, Google Chat delivery, self-scheduling cron, Claude Code plugin.

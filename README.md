```
▗▄▄  ▗▄▄▖  ▄▄▄ ▗▄▄▄▖▗▄▄▄▖     ▗▄▄  ▗▄▄▄▖▗▄▄▄▖▗▄▄▄▖  ▄▄ ▗▄▄▄▖ ▗▄▖ ▗▄▄▖ 
▐▛▀█ ▐▛▀▜▌ ▀█▀ ▐▛▀▀▘▝▀█▀▘     ▐▛▀█ ▐▛▀▀▘▝▀█▀▘▐▛▀▀▘ █▀▀▌▝▀█▀▘ █▀█ ▐▛▀▜▌
▐▌ ▐▌▐▌ ▐▌  █  ▐▌     █       ▐▌ ▐▌▐▌     █  ▐▌   ▐▛     █  ▐▌ ▐▌▐▌ ▐▌
▐▌ ▐▌▐███   █  ▐███   █       ▐▌ ▐▌▐███   █  ▐███ ▐▌     █  ▐▌ ▐▌▐███ 
▐▌ ▐▌▐▌▝█▖  █  ▐▌     █       ▐▌ ▐▌▐▌     █  ▐▌   ▐▙     █  ▐▌ ▐▌▐▌▝█▖
▐▙▄█ ▐▌ ▐▌ ▄█▄ ▐▌     █       ▐▙▄█ ▐▙▄▄▖  █  ▐▙▄▄▖ █▄▄▌  █   █▄█ ▐▌ ▐▌
▝▀▀  ▝▘ ▝▀ ▀▀▀ ▝▘     ▀       ▝▀▀  ▝▀▀▀▘  ▀  ▝▀▀▀▘  ▀▀   ▀   ▝▀▘ ▝▘ ▝▀
```

> **Know before it breaks.**

Drift Detector watches your codebase for third-party integrations that are **about to break** —
and tells you *which file and line* is affected, *with the date* it breaks, **before it does.**

It catches three kinds of rot:

1. **Retired vendor APIs** — a service you call (eBay, Amazon, Shopify, …) is **shutting down** an
   API your code still uses. *Example: "eBay's `GetCategoryFeatures` — called at
   `EbayCategoryFieldsFeature.php:72` — is retired as of 2026‑06‑04; migrate to the Taxonomy API."*
   **No SBOM or CVE scanner sees this** — it's the reason the tool exists.
2. **End-of-life software** — a runtime or framework version the maker no longer supports/patches.
3. **Known security holes** — public vulnerabilities in the packages you depend on.

**The main way to use it is a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin.**
Install it, point Claude at your code, and it runs **two engines together**: a **deterministic scan**
(the three above — dated, sourced, **zero AI tokens**) *and* an **AI cross-check** that surfaces
integrations the rules can't yet see. You get one report in **two clearly-separated tiers of trust** —
**certified findings** (machine-verified) and **AI leads** (gate-validated but not yet in the catalog,
and never mixed into the certified ones) — surfaced as **three planes** in one Cockpit (see below).
Where it *can't* see, it says so instead of reporting a false all-clear. *(It also runs headless on a
schedule for fleets — filing a ticket per problem in the repo that has it.)*

### The jargon, once (plain terms)

| Term | In plain English |
|---|---|
| **vendor-API sunset** | A third-party service is retiring an API your code calls. |
| **EOL** (end-of-life) | A software version the maker stopped supporting/patching. |
| **CVE** | A publicly-catalogued security hole in a software package. |
| **OSV** | The public database of those security holes (`osv.dev`) the tool checks against. |
| **SBOM** | A "bill of materials" — the list of every component your code depends on (standard CycloneDX/SPDX files, for compliance). |
| **SARIF** | A standard file format for code-scan results (GitHub code-scanning and VS Code read it). |
| **the Cockpit** | The interactive dashboard the tool publishes each run. |

- **How you run it:** a **Claude Code plugin** (the main way) · a standalone **CLI** (`uvx`/`pipx`,
  no clone) · or **headless on a schedule** for fleets — no server to operate.
- **What it's made of:** the deterministic core is Python (stdlib + PyYAML) + the **ast-grep**
  engine — **zero AI tokens**; the AI plane (in the plugin) adds *leads*, kept strictly separate.
- **Trustworthy by construction:** same inputs → identical output; every certified report is
  machine-verified before it's shown, and an AI lead can never enter it.

> Where it's headed: **[docs/ROADMAP.md](docs/ROADMAP.md)**.

---

## Use it in Claude Code (the main way)

Install the plugin, point it at a folder, and Claude runs the whole thing — separating the
**certified truth** from the **AI's guesses**. In the Claude Code CLI:

```
/plugin marketplace add TOPSinfo/drift-detector-scan
/plugin install drift-detector@tops-tools
/drift-detector:drift-detector /path/to/a/folder          # one repo, or a folder of repos
```

One command runs **all three planes** — CVE/EOL and vendor-API sunsets (certified) plus an AI
cross-check (leads) — then opens the **Cockpit** alongside a separate **AI · unverified** view.
Anything Claude learns about how a new integration is shaped persists to `~/.drift/catalog` and
makes every later run smarter. *(Needs [`uv`](https://docs.astral.sh/uv/); the plugin pulls the scan
engine from PyPI — nothing else to install.)*

---

## Use it as a CLI

Point it at any folder — a single project or a directory of many. **No token, no config, no
server**; the only network call is the audit step (to public CVE/EOL databases).

**Install-free** — with [uv](https://docs.astral.sh/uv/) (or `pipx`), no clone needed:

```
uvx --from drift-detector-scan drift-scan run --root ~/code/my-project --state /tmp/out --now $(date +%F)
# or:  pipx install drift-detector-scan   →   drift-scan run --root .
```

The scan engine (ast-grep) comes along as a pinned dependency — nothing else to install. (The
command is `drift-scan`; the PyPI package is [`drift-detector-scan`](https://pypi.org/project/drift-detector-scan/).)

**Or clone and run** — `bin/drift-scan` provisions its own Python venv + the engine on first run:

```
git clone https://github.com/TOPSinfo/drift-detector-scan && cd drift-detector-scan
./bin/drift-scan run    --root ~/code/my-project --state /tmp/out --now $(date +%F)
./bin/drift-scan verify --state /tmp/out
```

Either way, open `/tmp/out/dashboard.html` in a browser (or read `drift.md` in the terminal). Exit
codes make it CI-friendly: `0` ok · `2` error · `3` found problems · `4` couldn't scan / verify.

**Tidy up when you're done** — one command removes everything the tool wrote (it records each run,
so it finds the scattered `.drift-detector/` output folders for you), and it **keeps** your absorbed
catalog unless you ask otherwise:

```
drift-scan clean --report        # what's reclaimable — deletes nothing
drift-scan clean --all           # remove all run outputs + ~/.drift caches (keeps the catalog)
drift-scan clean --state /tmp/out # just one run's output
```

<p align="center">
  <img src="docs/screenshots/cli.png" alt="Install-free CLI run across several projects, then a self-consistency verify" width="840">
  <br><em>Install-free on real projects — one <code>uvx</code> command across several repos, then <code>verify</code> confirms the report is self-consistent.</em>
</p>

---

## Run it in CI (a fleet, on a schedule)

The CLI above is the hands-on way for a single developer. For **continuous, fleet-wide** coverage it also runs itself on a schedule — you **configure it once** and it reports without anyone invoking it.

```mermaid
flowchart TD
  SCHED["⏰ Schedule — GitHub Actions<br/>(free cloud compute, no server)"] --> RUN["drift-detector: one run"]
  RUN <-->|"read config + state,<br/>write state back"| OPS[("drift-ops — private Git repo<br/>config · fleet list · saved state")]
  RUN -->|"clone + scan"| FLEET["your fleet of repos"]
  RUN -->|"one ticket per problem"| ISSUES["issues, in each repo"]
  RUN -->|"publish"| COCKPIT["the Cockpit — dashboard"]
```

Two moving parts, clear roles:

- **The compute (GitHub Actions)** is just the *muscle* — it spins up, runs one scan, and
  disappears. There is **no always-on server.**
- **The `drift-ops` repo (on your GitLab) is the *brain*.** This is the "state repo" that stores
  everything the tool remembers between runs: the **config** (`drift.yml`), the **fleet** (which
  repos to scan), the **saved state** (last scan's results + the learned catalog), and it's where
  the **Cockpit is published from**. Each run reads from it and writes updated state back to it.

So the mental model is: **a scheduled robot that reads its instructions and memory from one private
Git repo, scans your other repos, and drops the results (tickets + dashboard) where your team
already works.** It is *not* a chat tool or a thing you invoke per-question.

---

## Configure it — `drift.yml`

`drift.yml` lives in the `drift-ops` repo and is the **one control surface** — everything the tool
does is set here (a reviewed commit, never a secret in the file):

```yaml
version: 1

# WHICH repos to scan — the "fleet". All https URLs on one host.
# A GROUP url scans every repo under it.
fleet:
  - https://git.example.com/team/service-a
  - https://git.example.com/team/service-b
  - https://git.example.com/platform            # a whole group

delivery:
  mode: create            # dry-run (print the plan, write nothing) · create (file issues) · off
  granularity: per-problem # how findings become tickets — see below
  devops:                 # DevOps tickets = package security + end-of-life
    assignee: ops-bot     #   assigned to this account (required when filing issues)
  developer:              # Developer tickets = retiring vendor APIs + framework EOL
    fallbackAssignee: lead #   auto-assigned to the repo's owner; this is the fallback

# Optional. `auth` holds env-var NAMES (never the secret itself); omit to use one GITLAB_TOKEN.
# notify: { gchat: GCHAT_WEBHOOK }
```

- **`mode`** — `dry-run` prints what it *would* file (safe to try); `create` actually files/updates
  issues; `off` skips delivery.
- **`granularity`** — how many tickets a repo's findings become:
  - `comprehensive` — **2 tickets per repo** (one DevOps, one Developer), each listing everything.
  - `per-vendor` — **one ticket per vendor** per repo (all dying eBay calls together, etc.).
  - `per-problem` — **one ticket per finding** (every dying API / package / EOL gets its own).
- **`devops` / `developer`** — the two audiences. Package-security & runtime-EOL tickets go to the
  DevOps account; retiring-vendor-API & framework-EOL tickets go to the **repo's owner** (resolved
  automatically), falling back to `fallbackAssignee`.

Re-runs **update tickets in place** (never duplicates); a fixed problem **closes its own ticket.**

**Setting it up (one-time).** In the GitHub repo that runs the schedule, set two repo **Variables** — `GITLAB_HOST` and `DRIFT_OPS_PATH` (your `drift-ops` repo path) — and one **Secret**, `GITLAB_TOKEN` (a bot token with `api` + `write_repository`). The schedule, fleet, and delivery all read from `drift-ops/config/drift.yml` — nothing else to wire.

---

## Architecture

The pipeline is **offline and deterministic** — same inputs produce byte-identical output, and it
spends **zero AI tokens.** Only the "audit" step reaches the network (to public databases).

```mermaid
flowchart LR
  SCAN["① scan<br/>find every integration<br/>(code + manifests)"] --> AUDIT["② audit<br/>check each against<br/>public databases"]
  AUDIT --> REPORT["③ certified report<br/>drift.json"]
  REPORT --> MD["drift.md"]
  REPORT --> DASH["the Cockpit<br/>3 planes"]
  REPORT --> ISS["GitLab issues"]
  AI["AI plane · plugin<br/>shape blind repos → absorb gate"] -. "gate-validated → AI Frontier" .-> DASH
```

The certified pipeline above is the deterministic, zero-token core. The **AI plane** (plugin only)
runs alongside it — shaping repos the scan can't read on its own — and its results reach the Cockpit
as the separate **AI Frontier** plane, gate-validated and never mixed into the certified numbers.

**① scan** — the [ast-grep](https://ast-grep.github.io) engine (a pinned static binary) finds the
third-party API calls in your source down to `file:line`, and manifest/lockfile parsing finds your
packages, runtimes, and frameworks. Output: `inventory.json` (the map of what you use).

**② audit** — each thing found is checked against three sources, and classified **act-now** or
**review**, always with a cited link:
- **OSV.dev** → known security holes (CVEs) per package version;
- **endoflife.date** → end-of-life runtimes/frameworks;
- **the vendor-sunset catalog** (`agent/vendor_sunsets.yaml`) → a **curated, dated, sourced** list
  of retiring vendor APIs, matched against the API calls found in step ①. *This is the layer no
  other scanner has.*

<p align="center">
  <img src="docs/screenshots/devops.png" alt="DevOps view — CVE and end-of-life findings grouped by rule" width="840">
  <br><em>The <b>DevOps view</b> — package security holes (OSV CVEs) and end-of-life findings, grouped by rule, each with the exact upgrade.</em>
</p>


**③ one report** — everything becomes `drift.json`, the **single source of truth.** The
human-readable `drift.md`, the Cockpit dashboard, the SBOM, and the filed issues are all
**projections** of it.

### Why you can trust it — `verify`

`drift-scan verify` **re-derives every projection from `drift.json` and fails if any disagrees.**
A green `verify` is the *only* claim the tool makes that a report is correct — nobody eyeballs the
dashboard for accuracy. It checks the dashboard's embedded data matches the report exactly, that
every dashboard tile's number equals the rows it filters to, and that nothing dated is silently
dropped. Two guarantees underpin everything:

- **"Cannot see" is never "clean."** If it can't read a repo (no access, unknown language), it says
  so and exits non-zero — never a false green checkmark.
- **Never invent a date.** Every retirement carries a source link fetched that run; undated ones
  say "no date announced." Nothing enters the catalog without passing a review gate.

### Detection — what it can see

Packages and security holes are table stakes. The **differentiator is the vendor-API layer**: it
knows *which third-party APIs your code calls* and *when the vendor kills them.*

```mermaid
flowchart LR
  CODE["your code + manifests"] --> PKG["packages · runtimes"]
  CODE --> API["API calls (file:line)"]
  PKG --> SEC["security holes + end-of-life"]
  API --> SUN["retiring vendor APIs (dated)"]
  SEC --> FIND["findings"]
  SUN --> FIND
```

It keeps up with new integration shapes through a **reviewed adaptation mechanism**: a shape it's
taught (as catalog data, never code) it detects deterministically forever after. It never adapts on
its own — every new shape passes the `absorb` review gate first (sourced dates, no false endpoints,
residue must shrink), so the tool learns without ever admitting an unverified finding.

<p align="center">
  <img src="docs/screenshots/vendors.png" alt="Integrations by vendor — which third-party APIs the code calls" width="840">
  <br><em><b>Which third-party APIs your code calls</b>, by vendor — the layer no SBOM or CVE scanner has (across a set of public seller-integration SDKs).</em>
</p>


### Delivery & the Cockpit

Findings roll up into **ranked jobs** (thirty security holes in one package = **one** upgrade job,
not thirty tickets), split by audience, and filed **in each repo's own tracker** — idempotently
(re-runs update in place; fixed problems auto-close). Each ticket carries an emoji-coded title
(🚨 past-due · ⏳ upcoming · ☣️ end-of-life · 🛡️ security), a 📊 link to the Cockpit, and a 🤖
**Open in Claude** link that pre-loads the finding so whoever picks it up gets full context.

The **Cockpit** is the interactive dashboard, organized as **three planes** — in decreasing order
of certainty, each with its own tiles and content:

- **Supply Chain** — CVEs and end-of-life software, plus the **SBOM** and **SARIF** exports (which
  live only here). The table-stakes supply-chain hygiene any SCA tool does.
- **Vendor Drift** *(certified)* — the retiring-vendor-API layer: a per-operation **retirement
  timeline** and the migration queue, proven to `file:line`. *The layer no other scanner has.*
- **AI Frontier** *(shaped)* — call-sites an AI recovered from code the deterministic scan couldn't
  read on its own, each re-checked and **gate-validated**, kept strictly out of the certified numbers.

Tiles and totals count **certified** findings only; the AI Frontier is always its own plane (and
shows an honest empty-state when no shaping ran). Published as a static site from the `drift-ops` repo.

<p align="center">
  <img src="docs/screenshots/cockpit.png" alt="The three-plane cockpit — Supply Chain, Vendor Drift, and AI Frontier over the vendor-API retirement timeline" width="840">
  <br><em>The <b>three-plane cockpit</b> — <b>Supply Chain</b> (CVE/EOL + SBOM/SARIF), <b>Vendor Drift</b> (the certified <b>Retirement Timeline</b>, past-due left of today), and the <b>AI Frontier</b> (shaped, gate-validated).</em>
</p>


---

## Outputs

| File | What it is |
|---|---|
| `inventory.json` | The map of everything your repos use (packages, runtimes, API calls at `file:line`). |
| `audit.json` | The findings + ranked jobs + what changed since last run. |
| **`drift.json`** | **The one report** everything else is derived from (and `verify`-checked against). |
| `dashboard.html` | The **Cockpit** — the interactive dashboard. |
| `drift.md` | The plain-text version of the report. |
| `sbom.json` / `*.sarif` | Standard SBOM (CycloneDX/SPDX) + SARIF exports for compliance/other tools. |

## What's built today

| Capability | Status |
|---|---|
| Deterministic scan → inventory of packages, runtimes & API calls (`file:line`) | ✅ |
| Security-hole (OSV) + end-of-life (endoflife.date) checks | ✅ |
| **Retiring-vendor-API detection** + the curated, dated, sourced catalog | ✅ |
| Reviewed adaptation (idiom families + the `absorb` intake gate) | ✅ |
| `drift.json` + `verify` (the trust contract) | ✅ |
| SBOM (CycloneDX/SPDX) + SARIF exports | ✅ |
| The Cockpit dashboard (tiles, retirement timeline, deep-links) | ✅ |
| Scheduled delivery: per-repo issues, 3 granularities, idempotent, "Open in Claude" | ✅ |

Where it's headed next: **[docs/ROADMAP.md](docs/ROADMAP.md)**.

---

## Repo map

```
bin/drift-scan       self-provisioning runner (fetches the pinned scan engine + a venv)
agent/               the pipeline: scan · audit · run · deliver · absorb (catalog intake)
agent/lib/           the pieces — engine, endpoint detection, OSV/EOL, ranking, delivery, verify, dashboard, config
agent/*.yaml         the reviewed catalogs — vendors · vendor_sunsets · idioms · frameworks
agent/assets/        the Cockpit — dashboard template + app + vendored runtime
.github/workflows/   scan.yml (the scheduled run)
docs/                ROADMAP.md · drift-absorb.md (catalog-intake doctrine) · EVAL.md · schema/ (the contract)
```

Working conventions for contributors: **[CLAUDE.md](CLAUDE.md)**.

## Limits (honest scope)

- API **version** is read from the URL on the matched line; it's `None` when a repo builds the URL
  from a base constant elsewhere (would need dataflow — out of scope).
- Only **directly-declared** dependencies are audited (not transitive ones pulled in by lockfiles).
- Security/EOL sources are OSV + endoflife.date; the vendor-sunset catalog is **curated** — you
  extend it (each entry cites a source).
- The dashboard shows the **latest** run; week-over-week history is a future layer (see the roadmap).

---

*Every finding is dated and sourced; every report is `verify`-certified; where it's blind, it says so.*
**Know before it breaks.**

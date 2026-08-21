# Drift Detector — Claude Code Plugin

> **Know before it breaks.** *AI proposes. The scanner adjudicates.*

Claude surfaces integrations the deterministic rules can't see yet; the scanner
proves them (`file:line`, sourced dates) or returns honest **needs-human**. The
heavy scan work is cheap, deterministic Python (ast-grep) — **zero LLM tokens** —
not an autonomous LLM agent.

## What it is

- **Slash command** `/drift-detector <folder> [more-folders...]` — runs a scan, points you at the
  report, and answers follow-up questions by querying the produced inventory (the "IR"), never by
  re-scanning. Run `/drift-detector` with no path and it asks which folder(s) to scan;
  `/drift-detector doctor` checks prerequisites.

The plugin ships **six commands**. `/drift-detector` is the one you need; the rest exist for when
a scan tells you it cannot see something, and each is documented under
[The other commands](#the-other-commands) below.

## Install (teammates)

The plugin is distributed as a Claude Code **marketplace** (this git repo). To install:

```
/plugin marketplace add https://github.com/TOPSinfo/drift-detector-scan
/plugin install drift-detector@tops-tools
```

Then run `/drift-detector <folder>` (see Use below). The first run bootstraps itself.

## Prerequisites

Just **`uv`** (recommended — https://docs.astral.sh/uv/) **or** python ≥ 3.11 with `venv`, and internet access on the first run. The bundled runner `bin/drift-scan` creates a plugin-local venv and installs the scan engine (ast-grep) itself — **no separate engine install, no manual Python setup**. Later runs reuse the venv. The scan **fails loud** if it can't provision the engine — no silent empty inventory.

## Use

```
/drift-detector /path/to/folder-of-cloned-repos
```

Git repos under `<folder>` are discovered **recursively** (at any depth). Pass multiple space-separated folders to scan several trees at once. The command:
1. checks the engine,
2. runs the scan (only repos whose git `HEAD` changed since last time are re-analyzed — a
   per-repo commit-SHA cache makes re-runs fast),
3. writes `<folder>/.drift-detector/{inventory.json, audit.json, dashboard.html}`,
4. narrates a summary (top APIs by repo count, runtimes/frameworks, what changed since last scan),
5. answers follow-ups (*"which repos use SP-API?"*, *"who's on an old Node?"*) from
   `inventory.json` — the queryable shape-map — without re-scanning.

## Autonomous mode — `/drift-detector schedule <folder>`

`/drift-detector <folder>` runs the full **scan → audit** pipeline (the `run` subcommand) and offers
to install a **cron job** (default Sundays 7am) that re-runs it deterministically — zero LLM tokens —
on this machine. The agent shows the exact crontab
line and confirms before touching your crontab; `unschedule <folder>` removes it. Config + `cron.log`
live in `<folder>/.drift-detector/`.

## Audit — `/drift-detector audit <folder>`

Runs on the folder's existing `inventory.json` and checks it against **OSV.dev** (CVEs per
package) + **endoflife.date** (EOL runtimes/frameworks), classifying findings **DEPRECATED /
REVIEW** with cited sources. Deterministic (stdlib HTTP, no extra dependency, zero LLM tokens),
graceful offline. Checks the **declared manifest floor** version — verify against lockfiles.

## Outputs

Written to `<folder>/.drift-detector/` (multi-source scans go to `~/.drift-detector/<slug>/`):

- **`drift.json`** — **the one report.** Everything else is a *verified projection* of it, checked
  against `docs/schema/drift-v1.schema.json`.
- **`drift.md`** — the same report in the terminal.
- **`dashboard.html`** — the Cockpit: self-contained interactive dashboard. Opens from `file://`.
- **`summary.html`** — the quick view (the coverage tree on its own page).
- **`chart.html`** — what changed across runs.
- **`inventory.json`** — the IR: per-repo `{runtimes, frameworks, sdks, endpoints[{vendor,domain,
  version,file_count,files:[path:line]}]}` + rollups + coverage.
- **`audit.json`** — findings + ranked actions + delta, as data.

Every run finishes with **`verify`**, which re-parses `drift.md` and the rendered HTML and fails if
either disagrees with `drift.json`. **A green `verify` is the only correctness claim the tool
makes** — see [How it stays honest](how-it-stays-honest.md).

## The other commands

`/drift-detector` is the one you run. The other five exist for a specific moment: **the scan told
you it could not see something**, and each closes a different kind of blindness. None of them can
write to the catalog directly — every one ends at a gate, and a human merges the result.

| command | run it when | what it produces |
|---|---|---|
| **`/drift-absorb <folder> [repo]`** | a repo came back **UNKNOWN** — the scanner sees calls it cannot attribute | Investigates the blind spots, proposes an [idiom](glossary.md#idiom) as staged YAML, and iterates with `absorb --check` until the attributed call-sites climb. Ends by opening an MR for review |
| **`/drift-research <folder>`** | a vendor is **UNAUDITED** — detected, but nobody has read its retirement list | Reads each uncatalogued vendor's own deprecation docs in the wild, gate-validates what it finds, and proposes sourced sunsets |
| **`/drift-refresh <state-dir> [vendor]`** | a vendor is **UNAUDITED or BLOCKED** and a machine *cannot* fetch its page — a seller portal, a login wall | Walks a human through each portal, turns what they paste into sourced catalog entries, gates them, and attests the vendor `CURRENT` |
| **`/drift-onboard <repo-path> [--fleet]`** | you want this running without anyone remembering to | Scaffolds a scheduled scan into the repo's CI (GitHub or GitLab), wires the API key as a secret, opens a PR/MR, and proves the run works |
| **`/drift-deepen`** | — | **Deprecated alias for `/drift-absorb`.** Kept so older habits and scripts keep working; it will be removed in a later release |

Two things they share, and they are the point:

- **A date nobody fetched does not exist.** `/drift-research` and `/drift-refresh` may only record
  a retirement with a `source:` URL read in that session. The [absorb gate](how-it-stays-honest.md)
  refuses a date without one. This project has been burned by plausible-but-wrong dates.
- **They propose; the scanner adjudicates.** `/drift-absorb` cannot widen a pattern to inflate its
  numbers — the gate re-scans the repo and rejects any attribution the proposal did not *claim*,
  and any claim outside the blind spots the scan flagged on its own.

## Notes & limits

- **Local folder(s)** input (clone orchestration is out of scope). Point it at one or more directories; repos are found recursively and multiple roots are deduped by real path.
- Endpoint **version** is best-effort from the URL on the matched line — `None` when a repo builds
  the URL from a base constant with the version appended elsewhere (needs dataflow).
- Detects hard-coded endpoints + manifest-declared SDKs; an SDK used only via its client library
  (no hard-coded URL) shows via the manifest, not as a call-site.
- Extend `agent/vendors.yaml` (vendors) and `agent/frameworks.yaml` (frameworks) as your stack grows.
- The audit uses Tier-1 sources (OSV + endoflife.date). Deferred: Tier 2 (registry abandoned/deprecated,
  e.g. `fzaninotto/faker`) + Tier 3 (community/early-warning) signals; lockfile-precise versions.
- Delivery from the plugin is **local files** (above) — plus optional GitLab issue filing when run
  from CI with a config. Deferred: email, code-scanning upload to the GitHub Security tab, fleet
  auto-clone, systemd-timer/launchd (cron is Linux/macOS).

# Public Positioning Hero Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unpark Claude-plugin-first public positioning and rewrite stranger-facing copy so the first screen reads *AI proposes. The scanner adjudicates.* without implying the certified scan is an LLM.

**Architecture:** Docs-only. Shared marketplace/plugin `description` string + README hero + PLUGIN.md lead + unpark banners. No product code, no version bump, no HTML/FRONTEND-PLANE.

**Tech Stack:** Markdown + JSON manifests in `/home/tops/Projects/tops/drift/drift-detector-scan`; orchestrator pointer in `/home/tops/Projects/tops/deprication-agent`.

## Global Constraints

- Tagline stays *Know before it breaks.*
- Boast frame is exactly: *AI proposes. The scanner adjudicates.*
- Forbidden: any wording that treats the certified scan path as model-driven (“AI-powered scanner” or equivalent).
- `plugin.json` and `marketplace.json` `description` must be **byte-identical**; `version` fields must remain **0.20.0-beta** (do not bump).
- CI/headless is a footnote under Use it, not a peer hero section.
- Empty AI Frontier = no pass / no shaping, not “clean.”
- Do not touch Shopify gap product files in this commit (`composer.py`, `sdk_clients.yaml`, eval corpus tests).
- Absolute shipping tree: `/home/tops/Projects/tops/drift/drift-detector-scan`

## File map

| File | Responsibility |
|------|----------------|
| `README.md` | GitHub first screen + install CTA + soft-claim hygiene in hero/Cockpit lead-ins |
| `.claude-plugin/plugin.json` | Claude plugin listing description |
| `.claude-plugin/marketplace.json` | Marketplace listing description (must match plugin) |
| `docs/PLUGIN.md` | Contributor/plugin doc lead paragraph |
| `docs/PUBLIC-POSITIONING-CLAUDE.md` | Unpark: ACTIVE, remove “do not start” |
| `../deprication-agent/docs/PARKED-public-positioning.md` | Replace with unparked pointer |

---

### Task 1: Shared plugin/marketplace description

**Files:**
- Modify: `/home/tops/Projects/tops/drift/drift-detector-scan/.claude-plugin/plugin.json` (`description` only)
- Modify: `/home/tops/Projects/tops/drift/drift-detector-scan/.claude-plugin/marketplace.json` (`plugins[0].description` only)

**Interfaces:**
- Produces: identical `DESCRIPTION` string used by Task 4 checklist

- [ ] **Step 1: Set both descriptions to this exact text**

```text
Know before it breaks. Claude proposes integrations the rules can't see yet; Drift Detector's deterministic scanner adjudicates — file:line, sourced dates, or honest needs-human. Never invents a date; AI leads stay separate from certified findings.
```

In both JSON files, replace only the `description` value (keep unicode escapes if the file style uses `\u2014`; em dash as `—` or `\u2014` is fine as long as both files match after parse).

- [ ] **Step 2: Verify versions still match and descriptions match**

```bash
cd /home/tops/Projects/tops/drift/drift-detector-scan
python3 -c '
import json
p=json.load(open(".claude-plugin/plugin.json"))
m=json.load(open(".claude-plugin/marketplace.json"))["plugins"][0]
assert p["version"]==m["version"]=="0.20.0-beta", (p["version"], m["version"])
assert p["description"]==m["description"], "description mismatch"
print("OK", p["version"], len(p["description"]))
'
```

Expected: `OK 0.20.0-beta <n>`

- [ ] **Step 3: Commit (plugin + marketplace only)**

```bash
cd /home/tops/Projects/tops/drift/drift-detector-scan
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "$(cat <<'EOF'
docs: align plugin marketplace blurb with boast frame

AI proposes; the scanner adjudicates — keep certified scan distinct
from Claude leads in the public listing text.
EOF
)"
```

---

### Task 2: README hero + CI footnote + soft-claim pass

**Files:**
- Modify: `/home/tops/Projects/tops/drift/drift-detector-scan/README.md` (lines ~1–85 hero/Use it; soft-touch Cockpit/AI Frontier ~165–181 if needed)

**Interfaces:**
- Consumes: boast frame from Global Constraints
- Produces: first-screen copy matching Task 4 grep checklist

- [ ] **Step 1: Replace the hero block after the ASCII logo**

Keep the ASCII art fence unchanged. Replace from the tagline blockquote through the paragraph ending at “three planes in one Cockpit” with:

```markdown
> **Know before it breaks.**

**AI proposes. The scanner adjudicates.**

Claude finds third-party integrations the rules can't see yet. Drift Detector
**proves** them — `file:line`, sourced retirement dates — or says **needs-human**.
The certified scan path is deterministic (**zero AI tokens**); it never invents a
date, and AI leads never mix into certified findings.

It catches three kinds of rot on the **certified** path:

1. **Retired vendor APIs** — a service you call (eBay, Amazon, Shopify, …) is **shutting down** an
   API your code still uses. *Example: "eBay's `GetCategoryFeatures` — called at
   `EbayCategoryFieldsFeature.php:72` — is retired as of 2026‑06‑04; migrate to the Taxonomy API."*
   **No SBOM or CVE scanner sees this** — it's the reason the tool exists.
2. **End-of-life software** — a runtime or framework version the maker no longer supports/patches.
3. **Known security holes** — public vulnerabilities in the packages you depend on.

It runs as a **[Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin**. Point Claude at
your code; `/drift-detector` runs the certified scan and an optional AI cross-check kept in a
**separate trust tier**. Where the tool *can't* see, it says so — never a false all-clear.

### The jargon, once (plain terms)
```

Leave the jargon table and following bullets as-is unless a bullet says the scan is AI-powered (if so, reword to “deterministic core + separate AI leads”).

- [ ] **Step 2: Rewrite `## Use it` — plugin CTA primary, CI as footnote**

Replace the current `## Use it` section (including `### Headless — CI, or on a schedule`) with:

```markdown
## Use it

Install the plugin, point it at a folder, and Claude runs the scan — keeping
**certified truth** separate from **AI leads**:

```
/plugin marketplace add TOPSinfo/drift-detector-scan
/plugin install drift-detector@tops-tools
/drift-detector /path/to/a/folder          # one repo, or a folder of repos
```

One command runs the certified planes (CVE/EOL + vendor-API sunsets) plus an optional AI
cross-check, then opens the **Cockpit**. Anything Claude learns about a new integration shape
persists to `~/.drift/catalog` only after the absorb gate — and makes later runs smarter.

*(First run provisions its own venv and fetches the pinned ast-grep engine — needs
[`uv`](https://docs.astral.sh/uv/) or Python 3.11+ with venv, nothing else to install.)*

> **Headless / CI footnote:** same slash command works unattended via
> `claude -p "/drift-detector <repo…>" --permission-mode bypassPermissions`
> (exit `0` ok · `2` error · `3` found problems · `4` couldn't scan/verify). Fleet CI is a
> later story — not the homepage.
```

(Ensure markdown fences are balanced when pasting — the outer README fence must not break.)

- [ ] **Step 3: Soft-claim pass on Cockpit / AI Frontier bullets**

In “### The Cockpit”, ensure the AI Frontier bullet says shaped / gate-validated leads kept out of certified numbers, and that an empty Frontier is an honest empty-state (no pass), not clean. If current text already matches, leave screenshots and structure unchanged.

- [ ] **Step 4: Grep soft-claim offenders in README**

```bash
cd /home/tops/Projects/tops/drift/drift-detector-scan
rg -n -i 'AI-powered scanner|AI powered scanner|the scan is (an )?AI|LLM.?scan' README.md || true
rg -n 'AI proposes|Know before it breaks|needs-human|Headless / CI footnote' README.md
```

Expected: no AI-powered-scanner hits; boast/tagline/footnote present.

- [ ] **Step 5: Commit README only**

```bash
cd /home/tops/Projects/tops/drift/drift-detector-scan
git add README.md
git commit -m "$(cat <<'EOF'
docs: rewrite README hero for Claude-plugin-first positioning

Lead with AI proposes / scanner adjudicates; demote CI to a footnote.
EOF
)"
```

---

### Task 3: PLUGIN.md lead + unpark positioning docs

**Files:**
- Modify: `/home/tops/Projects/tops/drift/drift-detector-scan/docs/PLUGIN.md` (opening ~lines 1–17)
- Modify: `/home/tops/Projects/tops/drift/drift-detector-scan/docs/PUBLIC-POSITIONING-CLAUDE.md`
- Modify: `/home/tops/Projects/tops/deprication-agent/docs/PARKED-public-positioning.md`

**Interfaces:**
- Consumes: same boast frame as Tasks 1–2

- [ ] **Step 1: Replace PLUGIN.md opening through “What it is” intro**

```markdown
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
```

Leave Install / Prerequisites / Use sections unchanged in substance.

- [ ] **Step 2: Unpark `docs/PUBLIC-POSITIONING-CLAUDE.md`**

Replace the title/header block with:

```markdown
# Public positioning — Claude plugin first (ACTIVE)

Unparked 2026-08-15. README + marketplace/plugin blurbs follow this brief.
Related (still parked): `docs/FRONTEND-PLANE.md` — do not start HTML hero work from this doc.
```

Delete lines that say “Do not start README/marketplace rewrite until unparked.” Keep Locked decisions and Do not lists. Under “When unparking”, mark items 1–3 done (or replace section with “Shipped: README hero, marketplace blurb, CI footnote. Still deferred: FRONTEND-PLANE / summary.html lead.”).

- [ ] **Step 3: Replace orchestrator pointer**

Write `/home/tops/Projects/tops/deprication-agent/docs/PARKED-public-positioning.md` as:

```markdown
# Public positioning — unparked (2026-08-15)

Claude-plugin-first positioning is **ACTIVE** in the shipping tree:

`/home/tops/Projects/tops/drift/drift-detector-scan/docs/PUBLIC-POSITIONING-CLAUDE.md`

Spec: `docs/superpowers/specs/2026-08-15-public-positioning-hero-design.md`  
Plan: `docs/superpowers/plans/2026-08-15-public-positioning-hero.md`

FRONTEND-PLANE remains parked separately.
```

(Optional rename to `docs/public-positioning.md` is out of scope — keep path to avoid broken links.)

- [ ] **Step 4: Commit shipping-tree docs; leave orchestrator file for the human’s other repo commit if needed**

```bash
cd /home/tops/Projects/tops/drift/drift-detector-scan
git add docs/PLUGIN.md docs/PUBLIC-POSITIONING-CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: unpark Claude positioning; align PLUGIN.md lead

Mark PUBLIC-POSITIONING active; open plugin doc with the boast frame.
EOF
)"
```

Orchestrator file lives outside this git repo — stage/commit there only if that tree is versioned and the human asks.

---

### Task 4: Soft-claim acceptance checklist

**Files:** none (verification only)

- [ ] **Step 1: Run the checklist**

```bash
cd /home/tops/Projects/tops/drift/drift-detector-scan
# forbidden
rg -n -i 'AI-powered scanner|AI powered scanner' README.md docs/PLUGIN.md .claude-plugin/*.json && exit 1 || echo 'no forbidden AI-scanner claim'
# required frame
rg -n 'AI proposes\. The scanner adjudicates' README.md docs/PLUGIN.md
rg -n 'ACTIVE' docs/PUBLIC-POSITIONING-CLAUDE.md
# versions + identical descriptions
python3 -c '
import json
p=json.load(open(".claude-plugin/plugin.json"))
m=json.load(open(".claude-plugin/marketplace.json"))["plugins"][0]
assert p["version"]==m["version"]=="0.20.0-beta"
assert p["description"]==m["description"]
print("manifests OK")
'
# CI not a ## peer section
rg -n '^### Headless' README.md && exit 1 || echo 'no Headless peer section'
rg -n 'Headless / CI footnote' README.md
echo 'CHECKLIST PASS'
```

Expected: `CHECKLIST PASS`. Fail the task if any assert exits non-zero.

- [ ] **Step 2: Report evidence to navigator/human**

Include: `pwd`, `git log -3 --oneline`, `git status -sb`, checklist exit code. Do not push (human PAT).

---

## Spec coverage (self-review)

| Spec requirement | Task |
|------------------|------|
| Boast + tagline on stranger surfaces | 1, 2, 3 |
| Plugin install only hero CTA; CI footnote | 2 |
| Soft-claim hygiene | 2 step 3–4, 4 |
| Unpark positioning + orchestrator pointer | 3 |
| No version bump; identical descriptions | 1, 4 |
| Non-goals (no HTML, no Shopify in this commit) | Global Constraints |

No TBD/placeholders. Docs plan uses grep/assert verification instead of pytest (no runtime behavior).

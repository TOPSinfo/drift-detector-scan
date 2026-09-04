# How it works

No jargon. If you know what an API is, this page will make sense.

## The problem, in one paragraph

Your software talks to other companies' software — a payment service, a shipping service, a
marketplace, an AI provider. Those companies **retire** the old ways of talking to them, on
published schedules. They announce it, usually a year ahead, on a page nobody on your team
reads. On the announced day, the code that was working stops working.

Nothing warns you. The code doesn't change. The tests still pass. The vendor just switches it
off at their end.

## What this tool does

It reads your code and answers three questions:

1. **Which outside services does this code actually call?** Not which ones you meant to use —
   which ones appear in the code, line by line.
2. **Has the vendor announced that any of them are being switched off?** Checked against each
   vendor's own published notice.
3. **Exactly where would that break us?** The file and line number, so someone can open it.

The result is a list like: *"This file, line 35, calls an AI model OpenAI is shutting down on
23 October. Here are the other six places."*

## How it reads your code

It does **not** run your code, and it does not send your code anywhere. It reads the text of
your files the way a very literal proof-reader would — looking for the tell-tale shapes of an
outside call:

- a web address of a known vendor (`api.stripe.com`)
- a version stamped into a path (`/admin/api/2023-10/`)
- an AI model's name (`gpt-3.5-turbo`)
- code that makes a network request at all

Then it matches what it found against a **catalogue** of announced retirements.

## The catalogue is the product

The catalogue is a reviewed list of "vendor X is switching off Y on date Z", and every entry
carries a link to the page that date was read from.

That rule is enforced by the tool, not by good intentions: **a date with no source is
refused.** This project was once given two retirement dates that sounded right and were both
wrong by days. Everything else here follows from not wanting that to happen again.

## "Nothing found" is not the same as "nothing wrong"

This is the part most tools get wrong, and the part worth understanding.

If the tool cannot read a file, cannot reach a repository, or has never checked a particular
vendor's announcements, it says so. It will not show you a green tick for something it never
looked at.

So a report can say **"0 problems found, and 6 vendors nobody has checked"** — and that is an
honest answer, not a contradiction. The second half tells you how much the first half is
worth.

## Where the numbers come from

Every report is machine-checked before you see it. The tool re-reads its own output and
confirms the summary matches the detail — if the headline says 22 call-sites, the tool
verifies there really are 22. A report that fails that check is not published.

That is why the answer to "can I trust this number?" is a command you can run, not an
assurance.

## What you get

| Output | What it's for |
|---|---|
| A report page | The readable summary — what's dying, when, and where |
| A dashboard | Click through by vendor, repo or urgency |
| Tickets | Filed automatically into your issue tracker, updated as things change |
| Machine files | Standard formats your other security tools can read |

Every number on those surfaces is explained in **[Reading the report](reading-the-report.md)**.

## What it does not do

- It does not fix anything. It tells you what to fix and where.
- It does not guess. If a vendor publishes no date, the report says there is no date.
- It does not see private repositories it has no access to — and it lists the ones it
  couldn't read, rather than leaving them out quietly.

---

## The words you'll see

| Term | In plain English |
|---|---|
| **vendor-API sunset** | A third-party service is retiring an API your code calls. |
| **EOL** (end-of-life) | A software version the maker stopped supporting or patching. |
| **CVE** | A publicly-catalogued security hole in a software package. |
| **OSV** | The public database of those security holes the tool checks against. |
| **leaked credential** | An API key, password, or secret committed into your code — found by scanning your git history, not just today's files. The report says where it is, never what it is. |
| **SBOM** | A "bill of materials" — the list of every component your code depends on. |
| **SARIF** | A standard file format for scan results that GitHub and VS Code can read. |
| **the Cockpit** | The interactive dashboard the tool publishes on each run. |
| **UNAUDITED** | We detected this vendor but have never checked its announcements. |
| **BLOCKED** | We tried to check, and could not — this vendor only publishes retirements behind a partner login. |
| **file:line** | The exact place in a file — `Orders.php:35` means line 35 of that file. |

---

## Where the code lives

For anyone reading the repository itself:

```
.claude-plugin/      plugin manifest + marketplace entry
commands/            the plugin commands — drift-detector · drift-research · drift-absorb · …
bin/drift-scan       self-provisioning engine the plugin calls (fetches the pinned scanner + a venv)
agent/               the pipeline: scan · audit · run · deliver · absorb (catalog intake)
agent/lib/           the pieces — engine, endpoint detection, OSV/EOL, ranking, delivery, verify, dashboard, config
agent/*.yaml         the reviewed catalogs — vendors · vendor_sunsets · idioms ·
                     catalog_attestations · host_reputation · sdk_clients ·
                     sdk_profiles · frameworks
agent/assets/        the Cockpit — dashboard template + app + vendored runtime
templates/ci/        CI templates copied into a CUSTOMER's repo by onboarding (not run here)
deploy/drift-ops/    template for the private state/config repo a fleet needs
eval/                the SCANNER corpus — public repos pinned at a SHA + the recall gate
evals/               the PROMPT corpus — promptfile discipline probes (different thing, easily confused)
docs/                the documentation site (mkdocs.yml) · schema/ (the drift.json contract)
tests/               the suite; each test comment pins a real shipped bug
```

`eval/` and `evals/` really are different things: the first measures whether the *scanner*
finds what it should; the second whether the *instructions given to the AI* keep their
load-bearing rules.

Conventions for contributors live in
[CLAUDE.md](https://github.com/TOPSinfo/drift-detector-scan/blob/master/CLAUDE.md).

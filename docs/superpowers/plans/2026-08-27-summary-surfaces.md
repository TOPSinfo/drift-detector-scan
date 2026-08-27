# Summary Surfaces Implementation Plan — `chat-summary` + email

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One rendered closing block that ends a CLI scan, and the same facts delivered by email
from an independent CI job.

**Architecture:** Two specs, one core. `agent/lib/digest.py` extracts the summary facts from
`drift.json` **once**; `chat_summary()` and `summary_mail()` are renderers over those facts.
Neither computes a figure of its own, so the chat block, the email and `drift.md` cannot disagree.

**Tech Stack:** Python 3.11+, stdlib + PyYAML at runtime (`smtplib`/`email.message` are stdlib),
`pytest`.

**Specs:** `docs/superpowers/specs/2026-08-27-chat-summary-design.md`,
`docs/superpowers/specs/2026-08-27-email-summary-design.md`

## Global Constraints

- **Runtime stays stdlib + PyYAML.** No template engine, no mail library, no HTTP client.
- **Every figure comes from the payload.** A renderer that computes a count is a defect: `drift.json`
  is the one contract and every surface is a verified projection of it.
- **I/O is injected.** SMTP transport is a parameter, as `http` is everywhere else. No test opens a
  socket.
- **"Cannot see" ≠ "clean".** The blind-spot section renders even when empty; an absent section is
  indistinguishable from one nobody wrote.
- **Prove a guard against its bug.** Each test must be seen to FAIL on the defect it targets.
- **No client identifiers in fixtures.** Public repo.

## Ground truth, verified against a real `drift.json` before planning

- `counts` — `fixes`, `reposAffected`, `reposScanned`, `unaudited`, `unknown`, `pastDue`,
  `sunsets`, `critical`, `eol`; plus `byOwner.{developer,devops}.{fixes,review}`.
- `delta` — `{new, resolved, persisting, mutedCount}`, built at `agent/lib/findings_state.py:97`.
  **It has no `comparedAgainst`**, so a first scan is indistinguishable from a week where
  everything changed. `catalogDelta` *does* carry `comparedAgainst` and
  `agent/lib/coverage_digest.py:70` already uses it for exactly this. Task 1 closes that gap.
- `actions[]` — `kind`, `ref`, `unit`, `date`, `status`, `owner`, `repo`, `repoLabel`,
  `finding_count`, `file_count`, `worst`, `recommendation`, `fix_version`.
- `catalog[]` — `vendor`, `verdict`, `callSites`, `reasons`.
- `shapes[]` — `repo`, `verdict`, `reasons`.
- `notify` config: `_NOTIFY = {"gchat"}` at `agent/lib/ops_config.py:55`, loaded by `_load_notify`
  (line 113), which resolves an env-var NAME rather than a secret.
- `_cmd_notify` (`agent/cli.py:1521`) is the shape to model the new commands on — and the one
  place whose best-effort behaviour the email command deliberately does NOT copy.

## File Structure

- `agent/lib/findings_state.py` — **modified**, one field (Task 1).
- `agent/lib/digest.py` — **created.** `summary_facts()`, the single extractor.
- `agent/lib/chat_summary.py` — **created.** The closing block renderer.
- `agent/lib/mail.py` — **created.** Subject + text + HTML, and the injected SMTP send.
- `agent/lib/ops_config.py` — **modified.** `notify.email`.
- `agent/lib/verify.py` — **modified.** One invariant.
- `agent/cli.py` — **modified.** `chat-summary` and `email-summary`.
- `commands/drift-detector.md` — **modified.** The output contract.
- `tests/test_digest.py`, `tests/test_chat_summary.py`, `tests/test_mail.py`,
  `tests/test_notify_email_config.py` — **created.**

---

### Task 1: The findings delta says what it compared against

**Files:** Modify `agent/lib/findings_state.py:97`; Test: `tests/test_digest.py` (create)

**Interfaces:** Produces `audit["delta"]["comparedAgainst"]` — the prior scan's date string, or
`None` when there was no prior scan. Task 2 reads it.

- [ ] **Step 1: Write the failing test**

```python
"""The delta must say what it compared against, or a first scan cannot be told apart from a week
in which every finding changed.

On a real fleet's first run the delta reported 349 `new` and 0 `resolved`. Rendered as
"🆕 349 new · ✅ 0 resolved" that reads as a catastrophic week; it was in fact the first
measurement. `catalogDelta` already carries `comparedAgainst` and coverage_digest.py:70 uses it
for exactly this distinction — the findings delta simply never got the same field.
"""
from agent.lib import findings_state


def test_the_delta_names_the_scan_it_compared_against(tmp_path):
    prior = {"generated": "2026-08-20", "findings": []}
    audit = {"generated": "2026-08-27", "findings": []}
    findings_state.apply(audit, prior)          # follow the real entry point's name
    assert audit["delta"]["comparedAgainst"] == "2026-08-20"


def test_a_first_scan_compares_against_nothing(tmp_path):
    audit = {"generated": "2026-08-27", "findings": []}
    findings_state.apply(audit, None)
    assert audit["delta"]["comparedAgainst"] is None
```

Read `findings_state.py` first and correct the entry-point name and signature above to match what
is actually there — the two assertions are the contract, not the call shape.

- [ ] **Step 2: Run it, confirm it fails on the missing key**

Run: `.venv/bin/python -m pytest tests/test_digest.py -q`
Expected: `KeyError: 'comparedAgainst'`.

- [ ] **Step 3: Add the field**

At `agent/lib/findings_state.py:97`, inside the `audit["delta"] = {...}` literal:

```python
        # What this delta is a delta AGAINST. Without it a first scan and a week in which
        # everything changed produce identical numbers, and a renderer cannot tell them apart —
        # a real fleet's first run reported 349 `new`, which reads as a catastrophe and was
        # simply the first measurement. Mirrors catalogDelta.comparedAgainst, which
        # coverage_digest.py already relies on for the same distinction.
        "comparedAgainst": (prior or {}).get("generated"),
```

- [ ] **Step 4: Green, then the full suite**

Run: `.venv/bin/python -m pytest -q` — the schema may pin `delta`'s shape; if a schema test fails,
add the property to `docs/schema/drift-v1.schema.json` rather than loosening the test.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/findings_state.py docs/schema/drift-v1.schema.json tests/test_digest.py
git commit -m "feat(delta): record what the delta compared against

A first scan and a week in which every finding changed produce identical
numbers, and nothing downstream could tell them apart. A real fleet's first run
reported 349 new / 0 resolved, which reads as a catastrophic week and was the
first measurement. catalogDelta already carries this field and coverage_digest
relies on it; the findings delta never got it."
```

---

### Task 2: `summary_facts()` — one extraction, three renderers

**Files:** Create `agent/lib/digest.py`; Test: `tests/test_digest.py` (append)

**Interfaces:** Produces

```python
def summary_facts(payload: dict, *, leads: int | None = None) -> dict:
    """Everything a summary surface needs, read from drift.json and computed nowhere else."""
```

returning keys: `fixes`, `review`, `repos_affected`, `repos_scanned`, `new`, `resolved`,
`compared_against`, `urgent` (`{ref, date, sites}` or `None`), `do_first` (≤3 action dicts),
`unaudited` (`[{vendor, call_sites}]`), `unknown_repos` (`[repo]`), `leads`, `generated`.
Tasks 3 and 6 consume this and nothing else.

- [ ] **Step 1: Write the failing tests**

```python
from agent.lib import digest

_PAYLOAD = {
    "generated": "2026-08-27",
    "counts": {"fixes": 12, "reposAffected": 16, "reposScanned": 18,
               "byOwner": {"devops": {"fixes": 10, "review": 30},
                           "developer": {"fixes": 2, "review": 4}}},
    "delta": {"new": [1, 2, 3], "resolved": [1], "comparedAgainst": "2026-08-20"},
    "actions": [
        {"kind": "sunset", "ref": "eBay", "unit": "svcs.ebay.com", "date": "2025-02-05",
         "status": "DEPRECATED", "file_count": 4, "finding_count": 4},
        {"kind": "cve", "ref": "npm/axios", "date": None, "status": "DEPRECATED",
         "file_count": 9, "finding_count": 9},
        {"kind": "sunset", "ref": "Walmart", "unit": "/v3/insights", "date": "2027-02-06",
         "status": "REVIEW", "file_count": 1, "finding_count": 1},
        {"kind": "cve", "ref": "npm/lodash", "date": None, "status": "REVIEW",
         "file_count": 2, "finding_count": 2},
    ],
    "catalog": [{"vendor": "UPS", "verdict": "UNAUDITED", "callSites": 1},
                {"vendor": "Stripe", "verdict": "CURRENT", "callSites": 9}],
    "shapes": [{"repo": "a", "verdict": "UNKNOWN"}, {"repo": "b", "verdict": "KNOWN"}],
}


def test_every_figure_comes_from_the_payload():
    f = digest.summary_facts(_PAYLOAD)
    assert f["fixes"] == _PAYLOAD["counts"]["fixes"]
    assert f["review"] == 34                     # summed across owners, not invented
    assert (f["repos_affected"], f["repos_scanned"]) == (16, 18)
    assert (f["new"], f["resolved"]) == (3, 1)
    assert f["compared_against"] == "2026-08-20"


def test_the_most_urgent_is_the_earliest_dated_sunset():
    """Not the first action, and not a CVE — 'urgent' means a date that has passed or is closest."""
    assert digest.summary_facts(_PAYLOAD)["urgent"]["ref"] == "eBay"
    assert digest.summary_facts(_PAYLOAD)["urgent"]["date"] == "2025-02-05"


def test_do_first_is_capped_at_three_and_keeps_payload_order():
    f = digest.summary_facts(_PAYLOAD)
    assert len(f["do_first"]) == 3
    assert [a["ref"] for a in f["do_first"]] == ["eBay", "npm/axios", "Walmart"]


def test_blind_spots_are_extracted_not_counted_from_counts():
    """`counts.unaudited` exists, but the NAMES are what a reader can act on."""
    f = digest.summary_facts(_PAYLOAD)
    assert f["unaudited"] == [{"vendor": "UPS", "call_sites": 1}]
    assert f["unknown_repos"] == ["a"]


def test_a_clean_payload_yields_zeroes_not_absences():
    """Every key must be present on a clean fleet, so a renderer never has to guess whether a
    missing key means zero or means the extractor changed."""
    f = digest.summary_facts({"generated": "2026-08-27", "counts": {}, "delta": {},
                              "actions": [], "catalog": [], "shapes": []})
    assert f["fixes"] == 0 and f["do_first"] == [] and f["unaudited"] == []
    assert f["urgent"] is None and f["compared_against"] is None


def test_leads_is_carried_through_not_read_from_disk():
    """The AI plane's count is INJECTED. summary_facts stays a pure function of the payload —
    it must not open leads.json, or it becomes untestable and couples two tiers."""
    assert digest.summary_facts(_PAYLOAD, leads=7)["leads"] == 7
    assert digest.summary_facts(_PAYLOAD)["leads"] is None
```

- [ ] **Step 2: Run, confirm every test fails on the missing module**
- [ ] **Step 3: Implement `agent/lib/digest.py`**

```python
"""The summary facts every surface shares — extracted from drift.json, computed nowhere else.

The chat block, the email and the Google Chat card are RENDERERS over this. None of them counts
anything itself, so none can disagree with the report or with each other. That is the same rule
every other surface follows: drift.json is the contract, everything else is a projection.
"""
from __future__ import annotations

_DO_FIRST = 3


def _review(counts: dict) -> int:
    by = counts.get("byOwner") or {}
    return sum((by.get(o) or {}).get("review", 0) for o in ("devops", "developer"))


def _urgent(actions: list) -> dict | None:
    """The earliest DATED retirement. A CVE has no date and cannot be 'most urgent' in the sense
    a reader means — the question is what dies first, not what is worst."""
    dated = [a for a in actions if a.get("date")]
    if not dated:
        return None
    a = min(dated, key=lambda x: x["date"])
    return {"ref": (a.get("ref") or "") + (f" {a['unit']}" if a.get("unit") else ""),
            "date": a["date"], "sites": a.get("file_count") or a.get("finding_count") or 0}


def summary_facts(payload: dict, *, leads: int | None = None) -> dict:
    counts = payload.get("counts") or {}
    delta = payload.get("delta") or {}
    actions = payload.get("actions") or []
    return {
        "generated": payload.get("generated"),
        "fixes": counts.get("fixes", 0),
        "review": _review(counts),
        "repos_affected": counts.get("reposAffected", 0),
        "repos_scanned": counts.get("reposScanned", 0),
        "new": len(delta.get("new") or []),
        "resolved": len(delta.get("resolved") or []),
        # None means "no prior scan", which is NOT the same as zero movement — see Task 1.
        "compared_against": delta.get("comparedAgainst"),
        "urgent": _urgent(actions),
        "do_first": actions[:_DO_FIRST],
        "unaudited": [{"vendor": c.get("vendor"), "call_sites": c.get("callSites", 0)}
                      for c in (payload.get("catalog") or [])
                      if c.get("verdict") and c["verdict"] != "CURRENT"],
        "unknown_repos": [s.get("repo") for s in (payload.get("shapes") or [])
                          if s.get("verdict") == "UNKNOWN"],
        # Injected, never read from disk: keeps this a pure function of the payload and keeps the
        # certified plane and the probabilistic plane from coupling here.
        "leads": leads,
    }
```

- [ ] **Step 4: Green** — `6 passed`
- [ ] **Step 5: Full suite**
- [ ] **Step 6: Commit** — `feat(digest): one extraction of the summary facts, three renderers over it`

---

### Task 3: `chat-summary` — the closing block

**Files:** Create `agent/lib/chat_summary.py`; modify `agent/cli.py`; Test: `tests/test_chat_summary.py`

**Interfaces:** Consumes `digest.summary_facts`. Produces `render(facts) -> str` and the
`drift-scan chat-summary --state <dir>` command.

- [ ] **Step 1: Write the failing tests**

Cover, each as its own test: the headline line equals the facts; the delta line says *"first
scan — no previous run to compare against"* when `compared_against is None`; the blind-spot
section renders `• nothing — every vendor CURRENT, every repo read` when both lists are empty;
the AI line is absent when `leads is None` and present when it is `0`; the block ends with
`Scan complete.` and the reports line; and a line-budget test — ≤ 30 lines given 50 actions.

The last two are the ones this whole change exists for. Write them first.

- [ ] **Step 2: Run, confirm failure**
- [ ] **Step 3: Implement the renderer and the command**

Follow the shape in the spec exactly. The command mirrors `_cmd_notify`'s structure: read
`<state>/drift.json`; a missing report is a skip with exit 0, not an error; pass
`leads=` from `<state>/leads.json` when it exists, counted in the *command*, never in the library.

- [ ] **Step 4: Green** · **Step 5: Full suite** · **Step 6: Commit**

---

### Task 4: `verify` covers the block

**Files:** Modify `agent/lib/verify.py`; Test: `tests/test_chat_summary.py` (append)

Follow `check_md_matches_payload`'s shape exactly — `check_*(payload) -> None`, raising
`Violation`, registered in `verify_payload`'s tuple. Re-render from the payload and fail if a
headline figure disagrees.

**Read the registration first and copy it; do not invent a second style.** A test must assert the
check is *registered*, not merely defined — a check nobody runs is a comment.

- [ ] Steps 1–6 as above, with the red proved by doctoring a payload's `counts.fixes`.

---

### Task 5: The command file's output contract

**Files:** Modify `commands/drift-detector.md`

- [ ] **Step 1: Replace §"Deliver the report" steps 1–6 with three**

```markdown
1. **Verify.** `"$SCAN" verify --state "$D"`. Non-zero means the surfaces disagree — say so and
   report no figure until it is resolved.
2. **Deliver.** Paste `drift.md` verbatim, then run the AI plane exactly as described below.
3. **Close.** Run `"$SCAN" chat-summary --state "$D"` and paste its output **last, verbatim**.
   Emit it exactly: do not re-summarise, re-order, add a headline, append next steps, or offer
   anything. If the user asks about scheduling, cleanup or blind spots, answer then.
```

- [ ] **Step 2: Move the cron mechanics, crontab line, `unschedule` and log paths** out of the
      scan flow and into the help/onboarding section, where someone asking will find them.
- [ ] **Step 3: Commit** — no tests; this is prose that changes model behaviour, and the spec's
      risk table already records that it cannot be enforced in code.

---

### Task 6: `mail.py` — subject, text, HTML

**Files:** Create `agent/lib/mail.py`; Test: `tests/test_mail.py`

**Interfaces:** `summary_mail(facts, *, report_url=None, run_url=None) -> (subject, text, html)`.
Consumes the same facts as Task 3. Task 7 sends it.

- [ ] Tests: the subject carries the headline figures; **both** parts are present and the text part
      is non-empty; the clean-fleet case renders "0 to fix" rather than an empty body; no HTML tag
      appears in the text part.
- [ ] Implement, green, full suite, commit.

---

### Task 7: SMTP transport and `email-summary`

**Files:** Modify `agent/lib/mail.py`, `agent/cli.py`; Test: `tests/test_mail.py` (append)

**Interfaces:** `send(smtp_url, msg, *, transport=None) -> None`; command
`drift-scan email-summary --state <dir> --config <drift.yml> [--report-url] [--run-url] [--dry-run]`.

- [ ] Tests: the transport receives every recipient, the configured `from`, and the subject; a
      `smtp://` URL whose STARTTLS fails **raises** rather than sending in cleartext; the SMTP URL
      never appears in stdout; `--dry-run` sends nothing; **no `notify.email` → exit 0**; **no
      `drift.json` → exit 0**; **transport raises → exit NON-ZERO.**
- [ ] That last test is the deliberate divergence from `_cmd_notify`. Its docstring must say why,
      because a later "make it consistent" edit will otherwise silently restore the swallow: the
      mail is sent every run, so its ABSENCE is informative, and a silent failure destroys that
      signal.
- [ ] Implement, green, full suite, commit.

---

### Task 8: `notify.email` config

**Files:** Modify `agent/lib/ops_config.py`; Test: `tests/test_notify_email_config.py`

- [ ] `_NOTIFY` becomes `{"gchat", "email"}`; the `email` block requires `to` (non-empty list),
      `from`, `smtp` (an env-var NAME); unknown keys refused by name; addresses shape-checked.
- [ ] Tests: each rejection asserted on its **specific** message and asserted **not** to be a
      generic fallthrough — the tmp_path in a `ConfigError` contains the test's own name, and a
      `pytest.raises(match=...)` will match it by accident. This has already happened once in this
      repo; do not repeat it.
- [ ] Implement, green, full suite, commit.

---

### Task 9: CI job and CHANGELOG

**Files:** `drift-fleet/.gitlab-ci.yml` (a DIFFERENT repository — do not edit from a session rooted
in the scanner without saying so), `CHANGELOG.md`

- [ ] A `notify-email` job in `deploy`, `needs: [drift-fleet-scan]`, opt-in behind its own variable
      in the style of the `pages` job's `$PAGES_PUBLISH` gate.
- [ ] CHANGELOG entries for both surfaces, stating plainly that the CLI's primary output changes
      for every existing user — not describing it as a tweak.
- [ ] Full suite, commit.

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| Closing block, always last | 3 + 5 |
| Pure projection of the payload | 2 |
| Blind-spot section renders when empty | 3 |
| One fixed footer line | 3 |
| `verify` covers the block | 4 |
| Line budget | 3 |
| AI leads untouched, named in one line | 3 (`leads` injected) + 5 |
| Email: multipart, recipients in config, SMTP env var | 6, 7, 8 |
| Email fails loudly | 7 |
| SMTP out of the scan path | 7 (its own command, its own job) |

**Placeholder scan:** Tasks 3, 6, 7, 8 describe their tests by assertion rather than pasting full
code. That is deliberate and bounded: each names every case and the reason it exists, and the
shapes are established by Tasks 1–2 which do carry complete code. Task 1's test names the entry
point as a *contract* and instructs the implementer to correct the call shape from the file —
because `findings_state.py`'s signature was not read before planning.

**Type consistency:** `summary_facts()` returns the key set listed in Task 2 and is destructured by
that name in Tasks 3 and 6. `leads` is `int | None` in both. `send(smtp_url, msg, *, transport)`
matches its tests.

**Deviation flagged for review:** `notify.chat_card()` still does its own extraction and is NOT
migrated onto `summary_facts()`. That leaves two extractors for one set of facts — the exact drift
this plan's core exists to prevent, one file away. It is left out because it changes a working,
tested surface for no user-visible gain, and bundling it would make an output change also a
refactor. It should be the first follow-up, and if `chat_card` and the new block ever disagree,
this is why.

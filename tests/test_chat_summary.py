"""The closing block that ends a CLI scan.

A PM ran the plugin, read the result, and was lost by what followed: the report arrived first and
five more blocks followed it, three of them asking him to decide something. The diagnosis is not
only that it was long — it never visibly ENDED, so a reader could not tell whether more was coming.

So the tool renders the block and the model pastes it, last. It is a pure function of drift.json
like every other surface, which also makes it the first chat output that `verify` can cover.
"""
from agent.lib import chat_summary
from tests.test_digest import _PAYLOAD


def _render(payload=None, **kw):
    from agent.lib import digest
    return chat_summary.render(digest.summary_facts(payload or _PAYLOAD, **kw))


# ── the two properties this change exists for ─────────────────────────────────────────────────

def test_the_block_ends_the_run_visibly():
    """'Scan complete' plus where the reports are. Without this the output trails off and a reader
    cannot tell the run finished — which is what actually confused the PM, more than the length."""
    out = _render().rstrip().splitlines()
    tail = "\n".join(out[-2:])
    assert "Scan complete" in tail, f"the block does not announce the end:\n{tail}"
    assert "drift.md" in tail and "drift.json" in tail, "the reader is not told where it landed"


def test_the_block_stays_within_its_line_budget():
    """It replaced a wall; it must not quietly become one. 50 actions, still a glance."""
    payload = {**_PAYLOAD, "actions": _PAYLOAD["actions"] * 13}
    n = len(_render(payload).rstrip().splitlines())
    assert n <= 30, f"the closing block has grown to {n} lines"


# ── honesty ───────────────────────────────────────────────────────────────────────────────────

def test_the_blind_spot_section_names_what_was_not_seen():
    out = _render()
    assert "UNAUDITED" in out and "UPS" in out
    assert "UNKNOWN" in out and " a" in out


def test_the_blind_spot_section_renders_even_when_there_is_nothing_to_report():
    """An absent section is indistinguishable from one nobody wrote. A clean fleet must be told it
    is clean, in the same place it would have been told it was not."""
    clean = {**_PAYLOAD, "catalog": [{"vendor": "Stripe", "verdict": "CURRENT", "callSites": 9}],
             "shapes": [{"repo": "b", "verdict": "KNOWN"}]}
    out = _render(clean)
    assert "could NOT see" in out
    assert "nothing" in out.lower()


# ── the delta ─────────────────────────────────────────────────────────────────────────────────

def test_a_first_scan_says_so_rather_than_reporting_movement():
    """A first run reports every finding as new. Rendering that as a week's change reads as a
    catastrophe — the real fleet's first run would have said '349 new'."""
    first = {**_PAYLOAD, "delta": {"new": [1] * 349, "resolved": [], "comparedAgainst": None}}
    out = _render(first)
    assert "349" not in out, "a first scan was rendered as if it were movement"
    assert "first scan" in out.lower()


def test_a_later_scan_reports_the_movement_and_names_the_baseline():
    out = _render()
    assert "3 new" in out and "1 resolved" in out and "2026-08-20" in out


# ── the AI plane ──────────────────────────────────────────────────────────────────────────────

def test_the_ai_line_is_absent_when_no_pass_ran():
    assert "AI pass" not in _render()


def test_the_ai_line_appears_for_zero_leads_too():
    """`leads=0` means the pass RAN and found nothing, which is a different claim from not running
    — the same distinction the whole product turns on."""
    out = _render(leads=0)
    assert "AI pass" in out and "0" in out
    assert "leads, not findings" in out, "the tier distinction must survive into the summary"


def test_the_ai_line_does_not_restate_the_leads():
    """They are already above, in full. This line accounts for the pass; it does not summarise it."""
    out = _render(leads=7)
    assert "7" in out
    assert len([l for l in out.splitlines() if "AI pass" in l]) == 1


# ── the footer ────────────────────────────────────────────────────────────────────────────────

def test_the_footer_is_one_line_and_never_a_pitch():
    out = _render()
    footer = [l for l in out.splitlines() if "just ask" in l]
    assert len(footer) == 1
    assert "crontab" not in out and "cron job" not in out, (
        "the scheduling pitch is back in the scan output")


def test_the_urgent_line_names_the_kind_of_death_correctly():
    """An EOL runtime does not 'retire' — it reaches end-of-life. The earliest dated risk is the
    right thing to surface (php 7.4 in 2022 IS more urgent than a 2027 API sunset), but calling it
    a retirement misnames it, and this line is the one a reader acts on first."""
    eol = {**_PAYLOAD, "actions": [
        {"kind": "eol", "ref": "php", "date": "2022-11-28", "status": "DEPRECATED",
         "file_count": 1, "finding_count": 1}]}
    assert "end-of-life" in _render(eol)
    assert "retires" not in _render(eol)

    sunset = {**_PAYLOAD, "actions": [
        {"kind": "sunset", "ref": "eBay", "unit": "svcs.ebay.com", "date": "2025-02-05",
         "status": "DEPRECATED", "file_count": 4, "finding_count": 4}]}
    assert "retires" in _render(sunset)


# ── a scan that read nothing ────────────────────────────────────────────────────────────────
# FOUND BY A USER, 2026-09-02. `run` refused correctly — "✗ scanned 0 repositories — this is NOT
# a clean result", exit 4 — and then chat-summary on the same state printed:
#
#     🔴 0 to fix · 🟠 0 to review · across 0 of 0 repos
#     What this scan could NOT see
#       • nothing — every vendor CURRENT, every repo read
#     Scan complete.
#
# "every repo read" when zero were read, and "Scan complete" when nothing ran. The block that
# exists to say `cannot see != clean` was rendering the emptiest possible scan as a clean bill.

from agent.lib import digest


def _empty_scan(unscannable=None):
    return {"generated": "2026-09-02",
            "counts": {"fixes": 0, "reposScanned": 0, "reposAffected": 0,
                       "byOwner": {"devops": {"fixes": 0, "review": 0},
                                   "developer": {"fixes": 0, "review": 0}}},
            "actions": [], "catalog": [], "shapes": [],
            "rootsUnscannable": unscannable or []}


def test_a_scan_that_read_nothing_is_not_reported_as_complete():
    out = chat_summary.render(digest.summary_facts(_empty_scan()))
    assert "Scan complete" not in out
    assert "every repo read" not in out


def test_a_scan_that_read_nothing_says_so_loudly():
    out = chat_summary.render(digest.summary_facts(_empty_scan()))
    low = out.lower()
    assert "0 repositories" in low or "no repositories" in low or "nothing was scanned" in low
    assert "not a clean" in low


def test_an_unreadable_root_is_named_in_what_it_could_not_see():
    """The fleet case: a repo that failed to clone belongs in this section by definition, and it
    was never consulted here — so a scan could lose a repo and this block would not mention it."""
    payload = _empty_scan([{"root": "https://g/example-org/acme-crm",
                            "reason": "could not clone: Connection reset by peer"}])
    out = chat_summary.render(digest.summary_facts(payload))
    assert "acme-crm" in out
    assert "Connection reset" in out or "could not clone" in out


def test_a_partial_scan_still_names_the_repo_it_could_not_read():
    """Not just the zero case — 51 of 52 read is also a blind spot the reader must see."""
    payload = _empty_scan([{"root": "https://g/example-org/acme-crm", "reason": "reset"}])
    payload["counts"]["reposScanned"] = 51
    out = chat_summary.render(digest.summary_facts(payload))
    assert "acme-crm" in out
    assert "Scan complete" in out          # it DID complete; it just did not cover everything

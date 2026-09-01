"""The access work-order: vendors whose retirement list cannot be read by anyone here.

`catalog_coverage` grades a BLOCKED vendor as real, unmeasured exposure — its call-sites keep
counting, exactly like ACCEPTED — and `freshness.due_for_refresh` then drops it, correctly: the
deprecation page sits behind a partner login, a 403, or a portal that does not resolve, so
re-reading it cannot clear it. Listing it as research work would keep that queue permanently
non-empty, and a list that is never empty stops being read.

That leaves a gap the dropping code names itself: a block "clears only when someone supplies
access". This module is that actor's surface. It is a DIFFERENT audience from the freshness
work-order — not the person who reads deprecation pages, the person who can obtain an account, a
credential, or an allow-list entry — and it asks for exactly one thing per vendor: the access.

Pair it with `coverage_state`'s `newlyBlocked` / `noLongerBlocked` for the notification. The
standing list belongs in an issue that updates in place; only the CHANGES are worth a push,
because a weekly restatement of four unchanging vendors is the same never-read list in another
channel.

Deterministic: `now` is a pipeline input, ordering is total, no wall-clock.
"""
from __future__ import annotations

from agent.lib.catalog_coverage import BLOCKED


def records(coverage_records: list) -> list:
    """The BLOCKED rows, loudest first.

    Ordered by call-sites descending, then vendor name, so the ranking is total and two identical
    scans render identically. Exposure is the only ordering that helps someone decide which
    access to chase first — 25 call-sites of Mirakl is worth more effort than one of Temu.
    """
    rows = [r for r in coverage_records if r.get("verdict") == BLOCKED]
    return sorted(rows, key=lambda r: (-r.get("callSites", 0), r.get("vendor", "")))


def _line(r: dict) -> str:
    vendor = r.get("vendor", "")
    sites = r.get("callSites", 0)
    why = (r.get("blocked") or "").strip() or "no reason recorded"
    checked = (r.get("checked") or "").strip()
    when = f" _(last attempt {checked})_" if checked else ""
    return f"- **{vendor}** — {sites} call-site(s). {why}.{when}"


def work_order_md(coverage_records: list, now: str) -> str:
    """The access work-order body (a `drift:blocked` issue), for whoever can supply credentials.

    Deliberately never mentions `/drift-refresh`. That skill re-reads a vendor's page, and the
    page cannot be read — that is the definition of this list. Pointing an admin at it would
    substitute a guaranteed-failing action for the one that works.
    """
    rows = records(coverage_records)
    if not rows:
        return ("# Access needed — none\n\n"
                "Nothing is blocked: every detected vendor's retirement list is readable from "
                "here.\n")

    total = sum(r.get("callSites", 0) for r in rows)
    L = [f"# Access needed — {len(rows)} vendor(s), {total} call-site(s) (as of {now})", "",
         "The scanner detects these vendors and **cannot read their retirement lists at all** — "
         "an account-gated portal, a 403, a host that does not resolve. Re-running the scan or "
         "the research pass cannot change that; only access can.", "",
         "**`0 findings` for these vendors is a blind spot we can name, not a clean result.** "
         "Their call-sites still count as unmeasured exposure, and they will keep counting until "
         "someone here can read the page.", "",
         "## What each one needs", ""]
    L += [_line(r) for r in rows]
    L += ["",
          "## What to do with this",
          "For each vendor: obtain a documentation/developer account, ask the vendor's contact "
          "for their deprecation policy in writing, or have the portal's host allow-listed. Then "
          "record what you were given — the page URL and its dated text — and the next scan "
          "audits it like any other vendor.",
          "",
          "If access genuinely cannot be obtained, that is a decision rather than a dead end: "
          "record it as an ACCEPTED disposition with an approver and an expiry, so the residual "
          "risk is signed for by a named person instead of sitting here unread. The call-sites "
          "keep counting either way — an accepted risk is still a real one.",
          "",
          "This issue updates itself each scan and closes when nothing is blocked.", ""]
    return "\n".join(L)

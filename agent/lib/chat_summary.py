"""The closing block that ends a CLI scan — rendered by the tool, pasted by the model.

Why the tool renders it rather than the model writing it:

  1. It ENDS. The old output delivered the report and then five more blocks, three of them asking
     the reader to decide something, so a reader could not tell whether more was coming. This
     block is always last and says "Scan complete".
  2. It is identical every run and between models. Every other surface this tool publishes is a
     verified projection of drift.json; the chat text was the exception — prose, uncovered by
     anything. Now `verify` can re-render it and refuse a document that disagrees.

A pure function of `digest.summary_facts()`. It counts nothing itself.
"""
from __future__ import annotations

_MAX_LINES = 30            # the budget its own test enforces; it replaced a wall, not joined one


def _headline(f: dict) -> str:
    return (f"🔴 {f['fixes']} to fix · 🟠 {f['review']} to review · "
            f"across {f['repos_affected']} of {f['repos_scanned']} repos")


def _delta(f: dict) -> str:
    # A first run reports every finding as new. Saying "349 new" there reads as a catastrophic
    # week when it is the first measurement — so say which it is, never a bare number.
    if not f["compared_against"]:
        return "🆕 first scan — no previous run to compare against"
    return (f"🆕 {f['new']} new · ✅ {f['resolved']} resolved "
            f"since {f['compared_against']}")


def _action_line(a: dict) -> str:
    ref = (a.get("ref") or "") + (f" {a['unit']}" if a.get("unit") else "")
    where = a.get("repoLabel") or a.get("repo") or ""
    sites = a.get("file_count") or a.get("finding_count") or 0
    fix = a.get("fix_version")
    if fix:
        tail = f" → {fix}"
    elif a.get("date"):
        # Same reason as the urgent line: an EOL runtime reaches end-of-life, it does not retire.
        tail = (f" · end-of-life {a['date']}" if a.get("kind") == "eol"
                else f" · retires {a['date']}")
    else:
        tail = ""
    return f"{ref}{tail} — {sites} site(s)" + (f" in {where}" if where else "")


def render(f: dict) -> str:
    """The block. Always emitted last, always verbatim."""
    L: list[str] = [_headline(f), _delta(f)]

    u = f.get("urgent")
    if u:
        verb = "reaches end-of-life" if u.get("kind") == "eol" else "retires"
        L.append(f"⏰ Most urgent: {u['ref']} {verb} {u['date']} — {u['sites']} site(s)")

    if f["do_first"]:
        L += ["", "Do first"]
        L += [f"  {i}. {_action_line(a)}" for i, a in enumerate(f["do_first"], 1)]

    # ALWAYS rendered, even with nothing to report. A missing section is indistinguishable from
    # one nobody wrote, and this section is the product's thesis: 0 findings for an unaudited
    # vendor is not evidence of health.
    L += ["", "What this scan could NOT see"]
    if not f["unaudited"] and not f["unknown_repos"]:
        L.append("  • nothing — every vendor CURRENT, every repo read")
    else:
        for v in f["unaudited"][:3]:
            L.append(f"  • {v['vendor']} UNAUDITED, {v['call_sites']} call-site(s) — "
                     f"0 findings there is not evidence of health")
        if len(f["unaudited"]) > 3:
            L.append(f"  • …and {len(f['unaudited']) - 3} more unaudited vendor(s)")
        if f["unknown_repos"]:
            names = ", ".join(f["unknown_repos"][:3])
            more = f" (+{len(f['unknown_repos']) - 3} more)" if len(f["unknown_repos"]) > 3 else ""
            L.append(f"  • {len(f['unknown_repos'])} repo(s) UNKNOWN — {names}{more}; "
                     f"/drift-absorb teaches the scanner what it missed")

    # `leads is None` means no AI pass ran; `0` means it ran and found nothing. Different claims.
    if f["leads"] is not None:
        L += ["", f"AI pass: {f['leads']} lead(s) raised above — leads, not findings; "
                  f"nothing entered drift.json"]

    L += ["", "Scan complete. Reports: drift.md · summary.html · dashboard.html · drift.json",
          "Weekly scheduling, cleanup and blind-spot absorption are available — just ask."]
    return "\n".join(L)

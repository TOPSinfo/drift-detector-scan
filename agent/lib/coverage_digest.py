"""The management digest: the absorption scoreboard, as a document someone can be sent.

WHY A SEPARATE SURFACE: the report answers "what is broken in these repos". This answers a
different question, asked by a different person — *are we keeping up with the catalog?* Going
deterministic means the catalog is the tool's memory, and a vendor nobody has audited renders
exactly like a healthy one unless something says otherwise. This is that something.

A PROJECTION of drift.json, never a second computation. Every figure is read from the payload,
because a digest that recomputed its own numbers could disagree with the report it summarises,
and then two artifacts quietly tell two readers different things.
`verify.check_digest_matches_coverage` enforces that; this module must never do arithmetic the
payload has not already done, beyond the two additions documented below.

Pure and deterministic: payload + `now` in, Markdown out. No I/O, no clock.
"""
from __future__ import annotations

from datetime import date

# How much notice before a signed disposition lapses. A lapse that surprises somebody is a
# lapse that gets rubber-stamped in a hurry; two months is enough to re-examine instead.
EXPIRING_SOON_DAYS = 60


def _days_until(expires, now: str):
    try:
        return (date.fromisoformat(str(expires)) - date.fromisoformat(now)).days
    except (ValueError, TypeError):
        return None


def _dispositions(catalog: list, verdict: str) -> list:
    return sorted((r for r in catalog if r.get("verdict") == verdict),
                  key=lambda r: (-r.get("callSites", 0), r.get("vendor", "")))


def render(payload: dict, *, now: str) -> str:
    s = payload.get("catalogSummary") or {}
    delta = payload.get("catalogDelta") or {}
    catalog = payload.get("catalog") or []

    current = s.get("current", 0)
    internal = s.get("internal", 0)
    # The only arithmetic here, and both are sums of payload figures rather than re-derivations:
    # what is settled (CURRENT + INTERNAL — see catalog_coverage.SETTLED), over everything
    # detected. ACCEPTED is deliberately NOT in the numerator: a named risk is not a checked one.
    settled = current + internal
    detected = (settled + s.get("stale", 0) + s.get("unaudited", 0)
                + s.get("blocked", 0) + s.get("accepted", 0))

    L = ["# Vendor catalog coverage",
         "",
         f"_Scan of {payload.get('generated', now)}._",
         "",
         "## Where we stand",
         "",
         f"**{settled} of {detected} detected vendors** have had their retirement list checked "
         f"or been signed off as having none to check.",
         "",
         f"- **{s.get('unauditedCallSites', 0)} call-site(s)** belong to vendors nobody has "
         f"checked. This is the size of the blind spot, and the number worth managing — a "
         f"vendor count alone flattens it.",
         f"- {s.get('unaudited', 0)} unaudited · {s.get('stale', 0)} stale · "
         f"{s.get('blocked', 0)} blocked (docs behind a login nobody here holds)",
         ""]

    # ── movement ──
    L += ["## What moved", ""]
    compared = delta.get("comparedAgainst")
    if not compared:
        L += ["There is **no previous scan** to compare against, so no movement can be reported. "
              "This is not a quiet week — it is the first measurement.", ""]
    else:
        rows = [("Newly checked", delta.get("newlyAttested") or []),
                ("Newly stale", delta.get("newlyStale") or []),
                ("Newly detected", delta.get("newlyDetected") or []),
                ("No longer called", delta.get("noLongerDetected") or [])]
        L.append(f"Compared against the scan of {compared}.")
        L.append("")
        if not any(v for _, v in rows):
            L += ["Nothing changed.", ""]
        else:
            for label, vendors in rows:
                if vendors:
                    L.append(f"- **{label}:** {', '.join(vendors)}")
            L.append("")
            if delta.get("newlyDetected"):
                L += ["", "A newly detected vendor is not counted as progress even when it "
                          "arrives already catalogued — nobody did that work this period.", ""]

    # ── human sign-offs, split by whether they actually settle anything ──
    inhouse = _dispositions(catalog, "INTERNAL")
    if inhouse:
        L += ["## Signed off — no further check possible", "",
              "Built in-house. There is no external vendor lifecycle, so these are genuinely "
              "settled rather than merely unexamined.", ""]
        for r in inhouse:
            a = r.get("approver") or {}
            L.append(f"- **{r.get('vendor')}** — {r.get('callSites', 0)} call-site(s). "
                     f"Approved by {a.get('name', '—')}, {a.get('role', '—')}. "
                     f"Expires {r.get('expires', '—')}.")
            if a.get("basis"):
                L.append(f"  - {a['basis']}")
        L.append("")

    accepted = _dispositions(catalog, "ACCEPTED")
    if accepted:
        L += ["## Risk accepted — still counted as unchecked", "",
              "A named person accepted the residual risk because the vendor publishes nothing "
              "findable. Accepting a risk does not measure it, so these call-sites remain in "
              "the blind-spot total above.", ""]
        for r in accepted:
            a = r.get("approver") or {}
            L.append(f"- **{r.get('vendor')}** — {r.get('callSites', 0)} call-site(s). "
                     f"Accepted by {a.get('name', '—')}, {a.get('role', '—')}. "
                     f"Expires {r.get('expires', '—')}.")
            if a.get("basis"):
                L.append(f"  - {a['basis']}")
        L.append("")

    # ── expiries ──
    soon = []
    for r in inhouse + accepted:
        days = _days_until(r.get("expires"), now)
        if days is not None and days <= EXPIRING_SOON_DAYS:
            soon.append((days, r))
    if soon:
        L += [f"## Expiring within {EXPIRING_SOON_DAYS} days", "",
              "On expiry these return to the work-list as unaudited. Re-examine before then, "
              "rather than re-signing under time pressure.", ""]
        for days, r in sorted(soon, key=lambda x: (x[0], x[1].get("vendor", ""))):
            when = "already lapsed" if days < 0 else f"in {days} day(s)"
            L.append(f"- **{r.get('vendor')}** — {r.get('expires')} ({when})")
        L.append("")

    return "\n".join(L).rstrip() + "\n"

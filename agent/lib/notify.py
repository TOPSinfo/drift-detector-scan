"""Push a scan summary to a Google Chat space as a rich CARD (cardsV2).

The push layer: reports + issues/MRs are pull; this pings a channel so the team knows a scan ran.

WHO THIS IS FOR. The dashboard is the surface everyone reads; this space is maintainers. A card
that repeats the dashboard's exposure numbers tells a maintainer nothing they cannot already see,
and buries the only part that is theirs: the vendors the scan could NOT audit. So the card leads
with what the tool could not do — vendors blocked on access, vendors nobody has checked, hosts
still unnamed — and keeps exposure to a single line for context.

The two maintainer lists are kept apart on purpose, for the reason `catalog_coverage` states:
BLOCKED needs an account or an allow-list entry from outside; UNAUDITED needs somebody to read a
page. Collapsing them sends a maintainer to do the wrong thing.

Opt-in — no webhook, no-op. `http` is injected (testable). The webhook URL is a secret, read from
the environment, never committed.
"""
from __future__ import annotations

from agent.lib.http_util import default_http

_MAX_FIRST = 6            # how many "do this first" rows to show
_MAX_VENDORS = 8          # how many vendors to name per maintainer list before summarising


def _by_verdict(payload: dict, verdict: str) -> list:
    """Detected vendors on one verdict, loudest first — call-sites is the order to work in."""
    rows = [r for r in (payload.get("catalog") or []) if r.get("verdict") == verdict]
    return sorted(rows, key=lambda r: (-r.get("callSites", 0), r.get("vendor", "")))


def _vendor_lines(rows: list, *, with_reason: bool) -> str:
    out = []
    for r in rows[:_MAX_VENDORS]:
        line = f"<b>{r.get('vendor', '')}</b> — {r.get('callSites', 0)} call-site(s)"
        if with_reason and (r.get("blocked") or "").strip():
            line += f"<br><i>{r['blocked'].strip()}</i>"
        out.append(line)
    if len(rows) > _MAX_VENDORS:
        out.append(f"<i>…and {len(rows) - _MAX_VENDORS} more</i>")
    return "<br>".join(out)


def _review(counts: dict) -> int:
    bo = counts.get("byOwner", {})
    return sum((bo.get(o) or {}).get("review", 0) for o in ("devops", "developer"))


def _label(a: dict) -> str:
    return (a.get("ref", "") + (f" {a['unit']}" if a.get("unit") else "")).strip()


def chat_card(payload: dict, *, report_url: str | None = None,
              run_url: str | None = None) -> dict:
    """The full Google Chat message (cardsV2) for a scan — pure function of the payload."""
    c = payload.get("counts", {})
    sections = []

    # ── what a maintainer has to act on, FIRST ──────────────────────────────────────────────
    blocked = _by_verdict(payload, "BLOCKED")
    if blocked:
        sites = sum(r.get("callSites", 0) for r in blocked)
        sections.append({
            "header": f"Cannot audit — {len(blocked)} vendor(s), {sites} call-site(s)",
            "widgets": [{"textParagraph": {"text":
                "Their retirement lists cannot be read from here at all. Re-running the scan "
                "cannot change that — only access can.<br><br>"
                + _vendor_lines(blocked, with_reason=True)}}]})

    unaudited = _by_verdict(payload, "UNAUDITED")
    if unaudited:
        sections.append({
            "header": f"Never checked — {len(unaudited)} vendor(s)",
            "widgets": [{"textParagraph": {"text":
                "Detected, readable, but nobody has read their deprecation page yet. "
                "<b>0 findings here means unaudited, not clean.</b><br><br>"
                + _vendor_lines(unaudited, with_reason=False)}}]})

    queued = ((c.get("coverage") or {}).get("queued") or 0)
    if queued:
        sections.append({
            "header": "Still unnamed",
            "widgets": [{"textParagraph": {"text":
                f"<b>{queued}</b> detected host(s) have no vendor named yet, so they can never "
                f"be audited for a retirement. They read as 0 findings until someone names them."}}]})

    exposure = (f"🔴 <b>{c.get('fixes', 0)}</b> to fix · "
                f"🟠 <b>{_review(c)}</b> to review "
                f"across {c.get('reposAffected', 0)}/{c.get('reposScanned', 0)} repo(s)")
    if c.get("pastDue"):
        exposure += f"<br>⏰ <b>{c['pastDue']}</b> already past their removal date"
    exposure += (f"<br>🧩 {c.get('sunsets', 0)} vendor-API sunset(s) · "
                 f"{c.get('critical', 0)} critical CVE(s) · "
                 f"❓ {c.get('unknown', 0)} unknown host(s)")
    sections.append({"header": "Exposure",
                     "widgets": [{"textParagraph": {"text": exposure}}]})

    # No developer fix-list here. It used to lead the card — package upgrades, one row each —
    # and it is exactly what made this message read as generic in a maintainers-only space: the
    # same list every week, addressed to nobody in the room. That work is already carried by the
    # per-repo issues and the dashboard.

    # Access CHANGES only. The standing list of blocked vendors lives in the drift:blocked
    # work-order, which updates in place; restating four unchanging vendors here every week
    # would be the never-read list `freshness.due_for_refresh` refuses to produce, in chat.
    delta = payload.get("catalogDelta") or {}
    newly = delta.get("newlyBlocked") or []
    cleared = delta.get("noLongerBlocked") or []
    if newly or cleared:
        lines = []
        if newly:
            lines.append("🔒 <b>Now unauditable:</b> " + ", ".join(newly)
                         + "<br><i>Their retirement list cannot be read from here — this clears "
                           "only when someone supplies access.</i>")
        if cleared:
            lines.append("🔓 <b>Access regained:</b> " + ", ".join(cleared))
        sections.append({"header": "Access needed",
                         "widgets": [{"textParagraph": {"text": "<br>".join(lines)}}]})

    buttons = []
    if report_url:
        buttons.append({"text": "Full report", "onClick": {"openLink": {"url": report_url}}})
    if run_url:
        buttons.append({"text": "Scan run", "onClick": {"openLink": {"url": run_url}}})
    if buttons:
        sections.append({"widgets": [{"buttonList": {"buttons": buttons}}]})

    return {"cardsV2": [{"cardId": "drift-scan", "card": {
        "header": {"title": "Drift Detector",
                   "subtitle": f"scan {payload.get('generated', '')} · "
                               f"{c.get('reposScanned', 0)} repo(s)".strip()},
        "sections": sections}}]}


def post(webhook: str, message: dict, *, http=None) -> None:
    """POST the message (a cardsV2 dict) to the webhook."""
    (http or default_http)(webhook, method="POST", body=message)

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

from urllib.parse import quote

from agent.lib.http_util import default_http

_MAX_FIRST = 6            # how many "do this first" rows to show
_SHOW_BEFORE_COLLAPSE = 5   # rows kept visible; the rest stay in the card, one tap away


def _by_verdict(payload: dict, verdict: str) -> list:
    """Detected vendors on one verdict, loudest first — call-sites is the order to work in."""
    rows = [r for r in (payload.get("catalog") or []) if r.get("verdict") == verdict]
    return sorted(rows, key=lambda r: (-r.get("callSites", 0), r.get("vendor", "")))


def _vendor_row(r: dict, *, with_reason: bool) -> dict:
    """One vendor as a decoratedText row: exposure above, name in the middle, reason below.

    A run-on paragraph of vendors is unreadable on a phone, which is where most of this space's
    members will see it. `wrapText` is on because the blocked reasons are full sentences and
    truncating one loses the only part that says what to obtain.
    """
    sites = r.get("callSites", 0)
    row = {"topLabel": f"{sites} call-site(s)",
           "text": f"<b>{r.get('vendor', '')}</b>",
           "wrapText": True}
    if with_reason and (r.get("blocked") or "").strip():
        row["bottomLabel"] = r["blocked"].strip()
    return {"decoratedText": row}


def _review(counts: dict) -> int:
    bo = counts.get("byOwner", {})
    return sum((bo.get(o) or {}).get("review", 0) for o in ("devops", "developer"))


def _label(a: dict) -> str:
    return (a.get("ref", "") + (f" {a['unit']}" if a.get("unit") else "")).strip()


def _stat_column(label: str, value, detail: str) -> dict:
    return {"horizontalSizeStyle": "FILL_AVAILABLE_SPACE",
            "horizontalAlignment": "START", "verticalAlignment": "TOP",
            "widgets": [{"decoratedText": {"topLabel": label,
                                           "text": f"<b>{value}</b>",
                                           "bottomLabel": detail, "wrapText": True}}]}


def _queue_chips(project_url: str) -> list:
    """Deep links to the two maintainer work-orders this card is about.

    A maintainer's next move is a filtered issue list, not the repo root — so the chips carry the
    label filter. Only emitted when the caller supplies a project URL: a chip pointing nowhere is
    worse than no chip.
    """
    base = project_url.rstrip("/")
    def issues(label):
        return f"{base}/-/issues?label_name%5B%5D={quote(label, safe='')}"
    return [{"text": "🔒 Access work-order",
             "onClick": {"openLink": {"url": issues("drift:blocked")}}},
            {"text": "❓ Research queue",
             "onClick": {"openLink": {"url": issues("drift:resolve")}}},
            {"text": "📚 Catalog", "onClick": {"openLink": {"url": f"{base}/-/tree/main/catalog"}}}]


def chat_card(payload: dict, *, report_url: str | None = None,
              run_url: str | None = None, project_url: str | None = None,
              icon_url: str | None = None) -> dict:
    """The full Google Chat message (cardsV2) for a scan — pure function of the payload."""
    c = payload.get("counts", {})
    sections = []

    # ── what a maintainer has to act on, FIRST ──────────────────────────────────────────────
    blocked = _by_verdict(payload, "BLOCKED")
    if blocked:
        sites = sum(r.get("callSites", 0) for r in blocked)
        widgets = [{"textParagraph": {"text":
            "🔒 Their retirement lists cannot be read from here at all. Re-running the scan "
            "cannot change that — <b>only access can</b>."}}]
        widgets += [_vendor_row(r, with_reason=True) for r in blocked]
        widgets.append({"divider": {}})
        sections.append({
            "header": f"Cannot audit — {len(blocked)} vendor(s), {sites} call-site(s)",
            # Never collapsed: this is the one list nobody else in the org can act on.
            "widgets": widgets})

    unaudited = _by_verdict(payload, "UNAUDITED")
    if unaudited:
        widgets = [{"textParagraph": {"text":
            "🔍 Detected and readable, but nobody has read their deprecation page yet. "
            "<b>0 findings here means unaudited, not clean.</b>"}}]
        widgets += [_vendor_row(r, with_reason=False) for r in unaudited]
        widgets.append({"divider": {}})
        sections.append({
            "header": f"Never checked — {len(unaudited)} vendor(s)",
            # EVERY vendor stays in the card. This list used to end in "…and N more", which
            # dropped the tail; collapsing keeps it and shows the loudest few by default.
            "collapsible": True,
            "uncollapsibleWidgetsCount": _SHOW_BEFORE_COLLAPSE,
            "widgets": widgets})

    queued = ((c.get("coverage") or {}).get("queued") or 0)
    if queued:
        sections.append({
            "header": "Still unnamed",
            "widgets": [{"decoratedText": {
                "topLabel": "resolution queue",
                "text": f"<b>{queued}</b> detected host(s) with no vendor named",
                "bottomLabel": "They can never be audited for a retirement until someone names "
                               "them, and read as 0 findings until then.",
                "wrapText": True}},
                {"divider": {}}]})

    exposure = (f"🔴 <b>{c.get('fixes', 0)}</b> to fix · "
                f"🟠 <b>{_review(c)}</b> to review "
                f"across {c.get('reposAffected', 0)}/{c.get('reposScanned', 0)} repo(s)")
    if c.get("pastDue"):
        exposure += f"<br>⏰ <b>{c['pastDue']}</b> already past their removal date"
    exposure += (f"<br>🧩 {c.get('sunsets', 0)} vendor-API sunset(s) · "
                 f"{c.get('critical', 0)} critical CVE(s) · "
                 f"❓ {c.get('unknown', 0)} unknown host(s)")
    # Two-up: the number to act on beside the number that says how late it already is. Columns
    # cap at 2, which is the right cap — a stat row people scan, not a table they read.
    sections.append({"header": "Exposure", "widgets": [
        {"columns": {"columnItems": [
            _stat_column("action required", c.get("fixes", 0),
                         f"{_review(c)} more to review · "
                         f"{c.get('reposAffected', 0)}/{c.get('reposScanned', 0)} repo(s)"),
            _stat_column("past their removal date", c.get("pastDue", 0),
                         f"of {c.get('sunsets', 0)} vendor-API sunset(s) · "
                         f"{c.get('critical', 0)} critical CVE(s)"),
        ]}},
        {"textParagraph": {"text": exposure}},
    ]})

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
    tail = []
    if buttons:
        tail.append({"buttonList": {"buttons": buttons}})
    if project_url:
        tail.append({"chipList": {"chips": _queue_chips(project_url)}})
    if tail:
        sections.append({"widgets": tail})

    header = {"title": "Drift Detector",
              "subtitle": f"maintainers · scan {payload.get('generated', '')} · "
                          f"{c.get('reposScanned', 0)} repo(s)".strip()}
    # Caller-supplied, because the tool ships no image: a broken imageUrl renders as a broken
    # avatar on EVERY message, which is worse than the default.
    if icon_url:
        header.update({"imageUrl": icon_url, "imageType": "CIRCLE",
                       "imageAltText": "Drift Detector"})
    return {"cardsV2": [{"cardId": "drift-scan", "card": {
        "header": header, "sections": sections}}]}


def post(webhook: str, message: dict, *, http=None) -> None:
    """POST the message (a cardsV2 dict) to the webhook."""
    (http or default_http)(webhook, method="POST", body=message)

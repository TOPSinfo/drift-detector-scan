"""Push a scan summary to a Google Chat space as a rich CARD (cardsV2).

The push layer: reports + issues/MRs are pull; this pings a channel so the team knows a scan
ran, with the exposure, the top things to do first, and buttons to the report + run. Opt-in —
no webhook, no-op. `http` is injected (testable). The webhook URL is a secret, read from the
environment, never committed.
"""
from __future__ import annotations

from agent.lib.http_util import default_http

_MAX_FIRST = 6            # how many "do this first" rows to show


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

    exposure = (f"🔴 <b>{c.get('fixes', 0)}</b> to fix · "
                f"🟠 <b>{_review(c)}</b> to review "
                f"across {c.get('reposAffected', 0)}/{c.get('reposScanned', 0)} repo(s)")
    if c.get("pastDue"):
        exposure += f"<br>⏰ <b>{c['pastDue']}</b> already past their removal date"
    exposure += (f"<br>🧩 {c.get('sunsets', 0)} vendor-API sunset(s) · "
                 f"{c.get('critical', 0)} critical CVE(s) · "
                 f"❓ {c.get('unknown', 0)} unknown host(s)")
    sections.append({"header": "Exposure", "widgets": [{"textParagraph": {"text": exposure}}]})

    urgent = [a for a in payload.get("actions", []) if a.get("status") == "DEPRECATED"][:_MAX_FIRST]
    if urgent:
        widgets = []
        for a in urgent:
            repo = a.get("repoLabel") or a.get("repo", "")
            when = a.get("date") or a.get("fix_version")
            widgets.append({"decoratedText": {
                "text": f"<b>{_label(a)}</b>",
                "bottomLabel": repo + (f" · {when}" if when else "")}})
        sections.append({"header": "Do this first", "widgets": widgets})

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

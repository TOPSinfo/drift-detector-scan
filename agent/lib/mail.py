"""The email summary — rendering, and an injected SMTP transport.

A sibling of `chat_summary`, over the same `digest.summary_facts()`. Neither counts anything, so
the mail cannot disagree with the report it summarises or with the block the CLI prints.

SMTP lives HERE and not in the scan path, which is the rule CONTEXT.md records: the scanner
renders, CI delivers, so no SMTP credential or network dependency enters a scan.
"""
from __future__ import annotations

import smtplib
import urllib.parse
from email.message import EmailMessage

_MAX_FIRST = 3


def _blind_spot_lines(f: dict) -> list[str]:
    """Rendered even when empty — an absent section is indistinguishable from one nobody wrote."""
    if not f["unaudited"] and not f["unknown_repos"]:
        return ["  nothing — every vendor CURRENT, every repo read"]
    out = [f"  {v['vendor']} {v.get('verdict') or 'UNAUDITED'}, {v['call_sites']} call-site(s) — "
           f"0 findings there is not evidence of health" for v in f["unaudited"][:3]]
    # A block clears by someone obtaining access, never by re-reading the page, so it is called
    # out separately from the research backlog above.
    if f.get("newly_blocked"):
        out.append("  access needed — now unauditable: "
                   + ", ".join(f["newly_blocked"]))
    if f.get("no_longer_blocked"):
        out.append("  access regained: " + ", ".join(f["no_longer_blocked"]))
    if f["unknown_repos"]:
        out.append(f"  {len(f['unknown_repos'])} repo(s) UNKNOWN — "
                   f"{', '.join(f['unknown_repos'][:3])}")
    return out


def _action_line(a: dict) -> str:
    ref = (a.get("ref") or "") + (f" {a['unit']}" if a.get("unit") else "")
    sites = a.get("file_count") or a.get("finding_count") or 0
    fix = a.get("fix_version")
    if fix:
        tail = f" → {fix}"
    elif a.get("date"):
        tail = (f" · end-of-life {a['date']}" if a.get("kind") == "eol"
                else f" · retires {a['date']}")
    else:
        tail = ""
    return f"{ref}{tail} — {sites} site(s)"


def summary_mail(f: dict, *, report_url: str | None = None,
                 run_url: str | None = None) -> tuple[str, str, str]:
    """(subject, text_body, html_body) — a pure function of the summary facts."""
    subject = (f"Drift Detector — {f['fixes']} to fix, {f['review']} to review "
               f"({f['repos_affected']}/{f['repos_scanned']} repos)")

    delta = ("first scan — no previous run to compare against" if not f["compared_against"]
             else f"{f['new']} new · {f['resolved']} resolved since {f['compared_against']}")

    T = [subject, "",
         delta]
    if f.get("urgent"):
        u = f["urgent"]
        verb = "reaches end-of-life" if u.get("kind") == "eol" else "retires"
        T.append(f"Most urgent: {u['ref']} {verb} {u['date']} — {u['sites']} site(s)")
    if f["do_first"]:
        T += ["", "Do first"] + [f"  {i}. {_action_line(a)}"
                                 for i, a in enumerate(f["do_first"][:_MAX_FIRST], 1)]
    T += ["", "What this scan could NOT see"] + _blind_spot_lines(f)
    links = [u for u in (report_url, run_url) if u]
    if links:
        T += [""] + links
    text = "\n".join(T) + "\n"

    def esc(x: str) -> str:
        return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    H = [f"<h2>{esc(subject)}</h2>", f"<p>{esc(delta)}</p>"]
    if f.get("urgent"):
        u = f["urgent"]
        verb = "reaches end-of-life" if u.get("kind") == "eol" else "retires"
        H.append(f"<p><b>Most urgent:</b> {esc(u['ref'])} {verb} {esc(u['date'])} — "
                 f"{u['sites']} site(s)</p>")
    if f["do_first"]:
        H.append("<h3>Do first</h3><ol>"
                 + "".join(f"<li>{esc(_action_line(a))}</li>"
                           for a in f["do_first"][:_MAX_FIRST]) + "</ol>")
    H.append("<h3>What this scan could NOT see</h3><ul>"
             + "".join(f"<li>{esc(l.strip())}</li>" for l in _blind_spot_lines(f)) + "</ul>")
    for u in links:
        H.append(f'<p><a href="{esc(u)}">{esc(u)}</a></p>')
    return subject, text, "".join(H)


def build(subject: str, text: str, html: str, *, sender: str, to: list) -> EmailMessage:
    """multipart/alternative. Both parts always — see the test for why HTML alone is not enough."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send(smtp_url: str, msg: EmailMessage, *, transport=None) -> None:
    """Send `msg` over `smtp_url` — `smtps://` for implicit TLS, `smtp://` upgraded with STARTTLS.

    `transport` is injected exactly as `http` is elsewhere, so no test opens a socket.

    TLS is NOT optional. A `smtp://` URL whose STARTTLS fails raises rather than falling back to
    cleartext: the body names client repositories, and a silent downgrade is worse than a failed
    send, which at least goes red where somebody sees it.

    Returns None and never echoes the URL — the password lives in it.
    """
    u = urllib.parse.urlparse(smtp_url)
    implicit = u.scheme == "smtps"
    port = u.port or (465 if implicit else 587)
    if transport is None:
        transport = smtplib.SMTP_SSL if implicit else smtplib.SMTP
    with transport(u.hostname, port, timeout=30) as srv:
        if not implicit:
            srv.starttls()
        if u.username:
            srv.login(urllib.parse.unquote(u.username),
                      urllib.parse.unquote(u.password or ""))
        srv.send_message(msg)

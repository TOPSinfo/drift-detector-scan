"""Google Chat push — a rich cardsV2 message. Pure card builder + injected POST."""
import json

from agent.lib import notify


_PAYLOAD = {"generated": "2026-07-27", "counts": {
    "fixes": 18, "reposAffected": 2, "reposScanned": 2, "pastDue": 18,
    "sunsets": 20, "critical": 0, "unknown": 1,
    "byOwner": {"devops": {"fixes": 0, "review": 0}, "developer": {"fixes": 18, "review": 2}}},
    "actions": [
        {"ref": "eBay", "unit": "GetCategorySpecifics", "status": "DEPRECATED",
         "date": "2022-04-22", "repoLabel": "example-org/ebayapi"},
        {"ref": "Amazon SP-API", "unit": "/catalog/v0", "status": "DEPRECATED",
         "date": "2026-06-30", "repoLabel": "example-org/amazonspapi"},
        {"ref": "eBay", "unit": "GetItem", "status": "REVIEW", "date": "2027-01-01",
         "repoLabel": "example-org/ebayapi"}]}


def _card(payload=_PAYLOAD, **kw):
    return notify.chat_card(payload, **kw)["cardsV2"][0]["card"]


def test_header_and_exposure_summarise_the_scan():
    card = _card(report_url="https://git.x/root/ops", run_url="https://gh/run/1")
    assert card["header"]["title"] == "Drift Detector" and "2026-07-27" in card["header"]["subtitle"]
    # Found by header, not by index: the maintainer sections come first when there is anything
    # for a maintainer to do, and a positional lookup would silently start asserting the wrong
    # section rather than failing.
    exposure = _text(_section(card, "Exposure"))
    assert "18</b> to fix" in exposure and "2</b> to review" in exposure
    assert "18</b> already past" in exposure and "20 vendor-API" in exposure
    assert "maintainers" in card["header"]["subtitle"]


def test_the_card_does_not_carry_the_developer_fix_list():
    """REMOVED deliberately. The card used to lead with a "Do this first" list of package
    upgrades — composer/phpoffice/phpspreadsheet, npm/handlebars and the like. That is developer
    work, it is already carried by the per-repo issues and the dashboard, and in a maintainers-
    only space it was the whole of what made the message read as generic: the same list every
    week, none of it addressed to the person reading it.

    What a maintainer cannot get anywhere else is what the scan could NOT do, and that is what
    the card leads with now."""
    headers = [s.get("header") for s in _card()["sections"]]
    assert "Do this first" not in headers


def test_buttons_link_the_report_and_run():
    card = _card(report_url="https://git.x/root/ops", run_url="https://gh/run/1")
    buttons = card["sections"][-1]["widgets"][0]["buttonList"]["buttons"]
    urls = {b["text"]: b["onClick"]["openLink"]["url"] for b in buttons}
    assert urls["Full report"] == "https://git.x/root/ops" and urls["Scan run"] == "https://gh/run/1"


def test_post_sends_the_card_dict_to_the_webhook():
    sent = {}

    def http(url, *, method="GET", body=None, timeout=20):
        sent.update(url=url, method=method, body=body)
        return {}
    notify.post("https://chat.example/hook", {"cardsV2": [{"cardId": "x"}]}, http=http)
    assert sent["url"] == "https://chat.example/hook" and sent["method"] == "POST"
    assert "cardsV2" in sent["body"]


def test_cli_no_webhook_is_a_noop(tmp_path, monkeypatch, capsys):
    import json
    from agent import cli
    (tmp_path / "drift.json").write_text(json.dumps(_PAYLOAD))
    monkeypatch.delenv("DRIFT_CHAT_WEBHOOK", raising=False)
    rc = cli.main(["notify", "--state", str(tmp_path)])
    assert rc == 0 and "skipping" in capsys.readouterr().out


def test_cli_posts_a_card_when_webhook_given(tmp_path, monkeypatch, capsys):
    import json
    from agent import cli
    from agent.lib import notify as n
    (tmp_path / "drift.json").write_text(json.dumps(_PAYLOAD))
    posted = {}
    monkeypatch.setattr(n, "post", lambda w, m, **k: posted.update(webhook=w, msg=m))
    rc = cli.main(["notify", "--state", str(tmp_path), "--webhook", "https://chat/hook",
                   "--report-url", "https://git.x/root/ops"])
    assert rc == 0 and posted["webhook"] == "https://chat/hook"
    assert "cardsV2" in posted["msg"] and "sent" in capsys.readouterr().out


# ── Access changes ──────────────────────────────────────────────────────────────────────────
# The standing list of blocked vendors lives in the drift:blocked work-order, which updates in
# place. The push channel carries only the CHANGES: a weekly restatement of four unchanging
# vendors is the never-read list `freshness.due_for_refresh` refuses to produce, moved to chat.

def _with_delta(**delta):
    d = dict(_PAYLOAD)
    d["catalogDelta"] = {"comparedAgainst": "2026-07-20", "newlyAttested": [], "newlyStale": [],
                         "newlyDetected": [], "noLongerDetected": [],
                         "newlyBlocked": [], "noLongerBlocked": []}
    d["catalogDelta"].update(delta)
    return d


def _headers(card):
    return [s.get("header", "") for s in card["sections"]]


def test_a_quiet_scan_carries_no_access_section():
    """Nothing changed — the work-order already holds the standing list."""
    assert "Access needed" not in _headers(_card(_with_delta()))


def test_a_newly_blocked_vendor_is_pushed():
    """The one transition that needs someone OUTSIDE the team, so it must not wait for anyone
    to open an issue tracker."""
    card = _card(_with_delta(newlyBlocked=["Mirakl"]))
    assert "Access needed" in _headers(card)
    text = str(card["sections"])
    assert "Mirakl" in text


def test_a_vendor_that_regained_access_is_pushed_too():
    """Good news closes the loop: whoever chased the credential learns it landed."""
    card = _card(_with_delta(noLongerBlocked=["THE ICONIC"]))
    text = str(card["sections"])
    assert "THE ICONIC" in text


def test_a_payload_without_a_delta_does_not_crash():
    """A first run has no baseline, and older payloads predate the key entirely."""
    assert "Access needed" not in _headers(_card(_PAYLOAD))


# ── the maintainer card ─────────────────────────────────────────────────────────────────────
# This space is maintainers-only; the dashboard is the surface everyone else reads. A card that
# repeats the dashboard's exposure numbers tells a maintainer nothing they cannot already see,
# and buries the one thing only they can act on: the vendors the tool could NOT audit. So the
# card leads with what the scan could not do, and keeps exposure as a single line for context.

def _maint(catalog=None, queued=0, **delta):
    d = dict(_PAYLOAD)
    d["catalog"] = catalog or []
    d["counts"] = dict(_PAYLOAD["counts"], coverage={"queued": queued})
    if delta:
        base = {"newlyBlocked": [], "noLongerBlocked": []}
        base.update(delta)
        d["catalogDelta"] = base
    return d


def _headers(card):
    return [s.get("header", "") for s in card["sections"]]


def _section(card, header):
    return next(s for s in card["sections"] if s.get("header") == header)


def _text(section):
    """All human-visible text in a section, whatever widget carries it — so a test asserts WHAT
    the card says, not which widget type happens to say it."""
    out = []
    for w in section["widgets"]:
        out.append(w.get("textParagraph", {}).get("text", ""))
        dt = w.get("decoratedText", {})
        out += [dt.get("topLabel", ""), dt.get("text", ""), dt.get("bottomLabel", "")]
    return " ".join(x for x in out if x)


_BLOCKED = [{"vendor": "Mirakl", "verdict": "BLOCKED", "callSites": 25,
             "blocked": "documentation portal is account-gated"},
            {"vendor": "Foxtail", "verdict": "BLOCKED", "callSites": 42,
             "blocked": "login-gated, no public developer portal"}]
_UNAUDITED = [{"vendor": "UPS", "verdict": "UNAUDITED", "callSites": 35},
              {"vendor": "Xero", "verdict": "UNAUDITED", "callSites": 13}]


def test_the_card_leads_with_what_could_not_be_audited():
    """Order is the message. A maintainer opening this should see the blocked vendors first."""
    card = _card(_maint(_BLOCKED + _UNAUDITED, queued=191))
    assert _headers(card)[0].startswith("Cannot audit")


def test_blocked_vendors_are_named_with_their_exposure_and_reason():
    card = _card(_maint(_BLOCKED, queued=0))
    t = _text(_section(card, [h for h in _headers(card) if h.startswith("Cannot audit")][0]))
    assert "Foxtail" in t and "42" in t
    assert "login-gated" in t          # WHY, so the admin knows what to obtain
    assert "Mirakl" in t and "25" in t


def test_blocked_vendors_are_ordered_by_exposure():
    """Foxtail's 42 call-sites outrank Mirakl's 25 — that is the order to chase access in."""
    card = _card(_maint(_BLOCKED, queued=0))
    t = _text(_section(card, [h for h in _headers(card) if h.startswith("Cannot audit")][0]))
    assert t.index("Foxtail") < t.index("Mirakl")


def test_unaudited_vendors_are_listed_separately_from_blocked():
    """Different work: one needs an account, the other needs somebody to read a page. Collapsing
    them sends a maintainer to do the wrong thing — the same split catalog_coverage insists on."""
    card = _card(_maint(_BLOCKED + _UNAUDITED, queued=0))
    hs = _headers(card)
    assert any(h.startswith("Never checked") for h in hs)
    t = _text(_section(card, [h for h in hs if h.startswith("Never checked")][0]))
    assert "UPS" in t and "35" in t
    assert "Mirakl" not in t


def test_the_unnamed_host_queue_is_reported():
    card = _card(_maint(_BLOCKED, queued=191))
    assert any("191" in _text(s) for s in card["sections"] if s.get("header"))


def test_exposure_survives_as_one_line_for_context():
    """Not removed — a maintainer still wants to know the scan found something."""
    card = _card(_maint(_BLOCKED, queued=0))
    assert "Exposure" in _headers(card)
    assert "18</b> to fix" in _text(_section(card, "Exposure"))


def test_a_clean_maintainer_view_says_so_rather_than_showing_empty_sections():
    """Nothing blocked and nothing unaudited is the goal state, and it should read as one."""
    card = _card(_maint([], queued=0))
    hs = _headers(card)
    assert not any(h.startswith("Cannot audit") for h in hs)
    assert not any(h.startswith("Never checked") for h in hs)


# ── card craft ──────────────────────────────────────────────────────────────────────────────
# An incoming webhook is one-way: "users can't interact with the webhook … Webhooks aren't
# conversational" (Google's own webhook guide). So no textInput, selectionInput, dateTimePicker,
# no buttons carrying an `action`, no dialogs. What IS available is decoratedText, dividers,
# collapsible sections, chips, columns and link buttons — and the card should use them.

def _widgets(section):
    return section["widgets"]


def test_each_blocked_vendor_is_its_own_row_not_a_run_on_paragraph():
    """A paragraph of concatenated vendors is unreadable on a phone. decoratedText gives each one
    a line: exposure above, vendor in the middle, the reason underneath."""
    card = _card(_maint(_BLOCKED, queued=0))
    sec = _section(card, [h for h in _headers(card) if h.startswith("Cannot audit")][0])
    rows = [w["decoratedText"] for w in _widgets(sec) if "decoratedText" in w]
    assert len(rows) == 2
    foxtail = next(r for r in rows if "Foxtail" in r["text"])
    assert "42" in foxtail["topLabel"]                       # exposure, above the name
    assert "login-gated" in foxtail["bottomLabel"]           # what to obtain, below it
    assert foxtail.get("wrapText") is True                   # reasons are long; don't truncate


def test_the_unaudited_section_collapses_instead_of_truncating():
    """24 vendors used to become "…and 16 more", which loses the tail entirely. A collapsible
    section keeps every one and shows the loudest few."""
    many = [{"vendor": f"V{i}", "verdict": "UNAUDITED", "callSites": 30 - i} for i in range(24)]
    card = _card(_maint(many, queued=0))
    sec = _section(card, [h for h in _headers(card) if h.startswith("Never checked")][0])
    assert sec.get("collapsible") is True
    assert sec.get("uncollapsibleWidgetsCount", 0) >= 1
    rows = [w for w in _widgets(sec) if "decoratedText" in w]
    assert len(rows) == 24                                   # every vendor present, none dropped
    assert "and 16 more" not in str(sec)


def test_sections_are_separated_by_dividers():
    card = _card(_maint(_BLOCKED + _UNAUDITED, queued=191))
    assert any("divider" in w for s in card["sections"] for w in s["widgets"])


def test_the_card_uses_no_widget_a_webhook_cannot_deliver():
    """A webhook is send-only. An interactive widget would render dead, or reject the message."""
    card = _card(_maint(_BLOCKED + _UNAUDITED, queued=191))
    blob = json.dumps(card)
    for banned in ("textInput", "selectionInput", "dateTimePicker", '"action"'):
        assert banned not in blob, banned


def test_buttons_are_links_because_only_links_work():
    card = _card(_maint(_BLOCKED, queued=0), report_url="https://x/r", run_url="https://x/run")
    btns = [b for s in card["sections"] for w in s["widgets"]
            if "buttonList" in w for b in w["buttonList"]["buttons"]]
    assert btns and all("openLink" in b["onClick"] for b in btns)


def test_exposure_is_a_two_up_stat_row():
    """Four numbers in one sentence is a wall. Columns (max 2) put the two that matter side by
    side, so the shape of the week is legible without reading."""
    card = _card(_maint(_BLOCKED, queued=0))
    sec = _section(card, "Exposure")
    cols = next(w["columns"] for w in sec["widgets"] if "columns" in w)
    assert len(cols["columnItems"]) == 2
    left, right = (str(c) for c in cols["columnItems"])
    assert "18" in left                      # to fix
    assert "18" in right                     # already past their removal date


def test_chips_deep_link_to_the_maintainer_queues():
    """A maintainer's next move is a filtered issue list, not the repo root. Chips carry them
    straight to the two work-orders this card is about."""
    card = _card(_maint(_BLOCKED, queued=5), project_url="https://git.x/root/ops")
    chips = [c for s in card["sections"] for w in s["widgets"]
             if "chipList" in w for c in w["chipList"]["chips"]]
    urls = " ".join(c["onClick"]["openLink"]["url"] for c in chips)
    assert "drift%3Ablocked" in urls or "drift:blocked" in urls
    assert "drift%3Aresolve" in urls or "drift:resolve" in urls
    # `label`, not `text`: the live API returns 400 INVALID_ARGUMENT on `text`, and the
    # whole message is dropped. This assertion is the guard against that regression.
    assert all(c.get("label") for c in chips)
    assert not any("text" in c for c in chips)


def test_no_chips_without_a_project_url():
    """Never invent a link. No project URL, no chips."""
    card = _card(_maint(_BLOCKED, queued=5))
    assert not [w for s in card["sections"] for w in s["widgets"] if "chipList" in w]


def test_the_header_image_is_optional_and_circular_when_set():
    """No image is shipped with the tool, and a broken imageUrl renders as a broken avatar on
    every message — so it is caller-supplied or absent."""
    assert "imageUrl" not in _card(_maint([], queued=0))["header"]
    card = _card(_maint([], queued=0), icon_url="https://cdn.x/mark.png")
    assert card["header"]["imageUrl"] == "https://cdn.x/mark.png"
    assert card["header"]["imageType"] == "CIRCLE"
    assert card["header"].get("imageAltText")


def test_a_rejected_card_is_reported_as_a_bug_not_an_outage(capsys, tmp_path, monkeypatch):
    """A 4xx means the card is malformed — ours to fix. Swallowing it identically to a network
    outage is how a broken card ships and every message silently stops arriving, which is
    exactly what happened when a chip carried `text` instead of `label`."""
    import urllib.error
    from agent import cli
    (tmp_path / "drift.json").write_text(json.dumps(_PAYLOAD))

    def boom(webhook, message, **kw):
        raise urllib.error.HTTPError("u", 400, "Bad Request", {}, None)

    monkeypatch.setattr(notify, "post", boom)
    args = type("A", (), {"state": str(tmp_path), "webhook": "https://hook",
                          "config": None, "report_url": None, "run_url": None,
                          "project_url": None, "icon_url": None})()
    assert cli._cmd_notify(args) == 0                 # still never reddens the pipeline
    err = capsys.readouterr().err
    assert "REJECTED" in err and "bug in the card" in err

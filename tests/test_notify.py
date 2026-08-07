"""Google Chat push — a rich cardsV2 message. Pure card builder + injected POST."""
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
    exposure = card["sections"][0]["widgets"][0]["textParagraph"]["text"]
    assert "18</b> to fix" in exposure and "2</b> to review" in exposure
    assert "18</b> already past" in exposure and "20 vendor-API" in exposure


def test_do_this_first_lists_action_required_with_clean_repo():
    widgets = _card()["sections"][1]["widgets"]
    assert _card()["sections"][1]["header"] == "Do this first"
    # only DEPRECATED actions, clean repo name in the bottom label
    assert any("GetCategorySpecifics" in w["decoratedText"]["text"] for w in widgets)
    assert any("example-org/ebayapi" in w["decoratedText"]["bottomLabel"] for w in widgets)
    assert all("GetItem" not in w["decoratedText"]["text"] for w in widgets)   # REVIEW excluded


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

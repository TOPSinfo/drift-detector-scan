import json
from agent import cli


def _state(tmp_path):
    drift = {"endpoints": [{"repo": "r1", "vendor": "eBay", "classified": True,
                            "domain": "api.ebay.com", "files": ["a.php:1"]}]}
    (tmp_path / "drift.json").write_text(json.dumps(drift))
    ai = {"meta": {"reposRead": 1, "tokens": 5}, "repos": [{"repo": "r1", "summary": "s",
          "integrations": [{"vendor": "Kogan", "host": "api.kgn.io", "endpoint": "x",
                            "file": "k.php", "line": "9", "retired": "unknown"}]}]}
    (tmp_path / "ai.json").write_text(json.dumps(ai))
    return str(tmp_path / "ai.json")


def test_leads_writes_a_versioned_document(tmp_path):
    ai = _state(tmp_path)
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai, "--now", "2026-08-12"])
    assert rc == 0
    doc = json.loads((tmp_path / "leads.json").read_text())
    assert doc["schema"] == "drift-leads/v1"
    assert doc["checked"] == "2026-08-12"
    assert doc["repos"][0]["integrations"][0]["vendor"] == "Kogan"
    assert set(doc["tally"]) == {"agree", "aiOnly", "toolOnly"}


def test_leads_writes_no_side_car_html(tmp_path):
    """The whole point of the change: one surface. A second dashboard must not reappear."""
    ai = _state(tmp_path)
    cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai, "--now", "2026-08-12"])
    assert not (tmp_path / "probabilistic.html").exists()


def test_leads_refuses_a_date_in_a_lead(tmp_path):
    """A date is a CERTIFIED-tier claim. A lead may only say WHETHER something is retired —
    `retired` is the tri-state yes/no/unknown. Letting a date through here would route an
    ungated model-produced date into the same document the certified data lives in."""
    _state(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "2026-01-01"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2
    assert not (tmp_path / "leads.json").exists()


def test_leads_refuses_a_date_hidden_in_another_field(tmp_path):
    """F2: the date guard used to apply _DATEISH only to `retired`, but `retired` is already a
    strict tri-state (yes/no/unknown) — a date could never legally live there anyway. The real
    leak was a free-text field like `note`: {"retired":"yes","note":"Sunset on 2026-03-01 per the
    changelog"} sailed straight through and rendered in the dashboard's Evidence column. The
    guard must inspect every string value of the record, not just one field."""
    _state(tmp_path)
    bad = tmp_path / "bad3.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "yes",
         "note": "Sunset on 2026-03-01 per the changelog"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2
    assert not (tmp_path / "leads.json").exists()


def test_leads_refuses_a_non_tristate_retired(tmp_path):
    _state(tmp_path)
    bad = tmp_path / "bad2.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "probably"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2


def test_leads_keeps_the_existing_refusals(tmp_path):
    _state(tmp_path)
    (tmp_path / "malformed.json").write_text('{"not": "the shape"}')
    assert cli.main(["leads", "--state", str(tmp_path),
                     "--ai-results", str(tmp_path / "malformed.json"), "--now", "2026-08-12"]) == 2
    (tmp_path / "norepo.json").write_text(json.dumps({"meta": {}, "repos": [{"integrations": []}]}))
    assert cli.main(["leads", "--state", str(tmp_path),
                     "--ai-results", str(tmp_path / "norepo.json"), "--now", "2026-08-12"]) == 2


def test_leads_needs_a_prior_scan(tmp_path):
    ai = tmp_path / "ai.json"
    ai.write_text('{"meta":{},"repos":[]}')
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(ai),
                     "--now", "2026-08-12"]) == 2

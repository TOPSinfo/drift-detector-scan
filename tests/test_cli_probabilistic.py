import json
from agent import cli


def _state(tmp_path):
    drift = {"endpoints": [{"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]}]}
    (tmp_path / "drift.json").write_text(json.dumps(drift))
    ai = {"meta": {"reposRead": 1, "tokens": 5}, "repos": [{"repo": "r1", "summary": "s",
          "integrations": [{"vendor": "Kogan", "endpoint": "x", "file": "k.php", "line": "9",
                            "retired": "unknown"}]}]}
    (tmp_path / "ai.json").write_text(json.dumps(ai))
    return str(tmp_path / "drift.json"), str(tmp_path / "ai.json")


def test_probabilistic_writes_labelled_html(tmp_path):
    _state(tmp_path)
    rc = cli.main(["probabilistic", "--state", str(tmp_path),
                   "--ai-results", str(tmp_path / "ai.json"), "--now", "2026-07-31"])
    assert rc == 0
    html = (tmp_path / "probabilistic.html").read_text()
    assert "AI · unverified" in html and "Kogan" in html


def test_probabilistic_rejects_malformed_ai_results(tmp_path):
    _state(tmp_path)
    (tmp_path / "bad.json").write_text('{"not": "the shape"}')
    rc = cli.main(["probabilistic", "--state", str(tmp_path),
                   "--ai-results", str(tmp_path / "bad.json"), "--now", "2026-07-31"])
    assert rc == 2                                          # missing "repos" -> refused
    assert not (tmp_path / "probabilistic.html").exists()


def test_probabilistic_rejects_repo_entry_missing_repo_key(tmp_path):
    _state(tmp_path)
    (tmp_path / "bad.json").write_text(json.dumps({"meta": {}, "repos": [{"integrations": []}]}))
    rc = cli.main(["probabilistic", "--state", str(tmp_path),
                   "--ai-results", str(tmp_path / "bad.json"), "--now", "2026-07-31"])
    assert rc == 2                                          # repo entry missing "repo" -> refused
    assert not (tmp_path / "probabilistic.html").exists()


def test_probabilistic_needs_a_prior_scan(tmp_path):
    ai = tmp_path / "ai.json"; ai.write_text('{"meta":{},"repos":[]}')
    rc = cli.main(["probabilistic", "--state", str(tmp_path),
                   "--ai-results", str(ai), "--now", "2026-07-31"])
    assert rc == 2                                          # no drift.json -> refused


def test_probabilistic_refuses_corrupt_drift_json(tmp_path):
    (tmp_path / "drift.json").write_text("not json")
    ai = tmp_path / "ai.json"; ai.write_text('{"meta":{},"repos":[]}')
    rc = cli.main(["probabilistic", "--state", str(tmp_path),
                   "--ai-results", str(ai), "--now", "2026-07-31"])
    assert rc == 2                                          # corrupt drift.json -> refused, no traceback
    assert not (tmp_path / "probabilistic.html").exists()

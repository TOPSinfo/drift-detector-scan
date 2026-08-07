import json
import os
import pytest
from agent.eval import runner


_CORPUS = """
- repo: o/ebay-sdk-php
  url: https://github.com/o/ebay-sdk-php.git
  sha: "{sha}"
  license: MIT
  category: ebay
  expect: {{ vendor: eBay, sunset_host: svcs.ebay.com }}
  fetched_at: "2026-07-16"
""".format(sha="a" * 40)


def _corpus_file(tmp_path):
    p = tmp_path / "corpus.yaml"
    p.write_text(_CORPUS)
    return str(p)


def _fake_scan(root, state, now, **kw):
    # one repo, one classified eBay endpoint — as if scanned
    doc = {"repos": [{"path": "ebay-sdk-php",
                      "endpoints": [{"vendor": "eBay", "classified": True, "version": "v1",
                                     "domain": "svcs.ebay.com"}],
                      "sdks": []}],
           "coverage": {"reposErrored": []}}
    return {"doc": doc, "diff": {}}


def _fake_audit(doc, now, **kw):
    return {"findings": [{"kind": "sunset", "domain": "svcs.ebay.com", "ref": "eBay"}]}


def test_run_category_scores_writes_and_passes_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path / "drift"))
    sc = runner.run_category("ebay", now="2026-07-16", sandbox_root=str(tmp_path / "sandbox"),
                             corpus_path=_corpus_file(tmp_path),
                             git=lambda args, cwd=None: ("a" * 40 if "rev-parse" in args else ""),
                             scan=_fake_scan, audit=_fake_audit)
    assert sc["gate"]["passed"] is True
    assert sc["now"] == "2026-07-16"
    assert sc["summary"]["sunset_match"] == {"expected": 1, "hit": 1}
    # scorecard.json written under eval_home/runs/<now>/<category>/
    out = tmp_path / "drift" / "eval" / "runs" / "2026-07-16" / "ebay" / "scorecard.json"
    assert out.exists() and json.loads(out.read_text())["gate"]["passed"] is True
    # a history line appended
    hist = tmp_path / "drift" / "eval" / "scorecards" / "history.jsonl"
    assert hist.exists() and "ebay" in hist.read_text()


def test_cli_returns_exit_code_from_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path / "drift"))
    from agent.eval import cli
    # a scan that detects nothing -> gate fails -> exit 1
    monkeypatch.setattr(runner, "scan_folder",
                        lambda *a, **k: {"doc": {"repos": [{"path": "ebay-sdk-php",
                                                            "endpoints": [], "sdks": []}],
                                                "coverage": {"reposErrored": []}}, "diff": {}})
    monkeypatch.setattr(runner, "audit_inventory", lambda *a, **k: {"findings": []})
    rc = cli.main(["run", "ebay", "--now", "2026-07-16", "--no-clone",
                   "--sandbox", str(tmp_path / "sandbox"), "--corpus", _corpus_file(tmp_path)])
    assert rc == 1


@pytest.mark.skipif(not os.environ.get("DRIFT_EVAL_LIVE"),
                    reason="opt-in live smoke (set DRIFT_EVAL_LIVE=1); clones a real repo, runs the engine")
def test_live_smoke_one_real_ebay_repo(tmp_path, monkeypatch):
    # Uses the committed eval/corpus.yaml; scores the FIRST entry's repo for real.
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path / "drift"))
    sc = runner.run_category("ebay", now="2026-07-16", sandbox_root=str(tmp_path / "sandbox"),
                             corpus_path="eval/corpus.yaml")
    assert sc["gate"]["passed"] is True
    assert any(r["detected"] for r in sc["repos"])

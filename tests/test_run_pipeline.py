import json
import subprocess
from pathlib import Path

from agent.run import run_pipeline


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _empty_engine(args):
    return json.dumps([])


def _fake_eol(product, version, now, *, http=None):
    if (product, version) == ("php", "7.4"):
        return {"product": "php", "slug": "php", "cycle": "7.4", "status": "DEPRECATED",
                "eol_date": "2022-11-28", "latest": "8.3", "recommended": "8.3.10",
                "source_url": "https://endoflife.date/php"}
    return None


def test_run_pipeline_writes_all_reports_and_delivers(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^7.4"}}'})
    state = tmp_path / "state"

    # audit uses the module's eol.check via audit_inventory; patch it to avoid network
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.eol, "check", _fake_eol)

    posted = {}

    def fake_http(url, *, method="GET", body=None, timeout=20):
        posted["url"] = url
        posted["body"] = body
        return {}

    out = run_pipeline(str(root), str(state), "2026-07-15",
                       engine="semgrep", run=_empty_engine, http=fake_http)

    for name in ("inventory.json", "audit.json", "dashboard.html", "chart.html",
                 "drift.md", "drift.json"):
        assert (state / name).exists(), name
    # the ONLY report surface on hybrid: nothing else is written
    assert not (state / "INVENTORY.md").exists() and not (state / "AUDIT.md").exists()
    assert not (state / "DRIFT.md").exists() and not (state / "bom.json").exists()
    assert out["auditCounts"]["DEPRECATED"] >= 1


def test_run_pipeline_pull_invokes_git_per_repo(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "a", {"composer.json": "{}"})
    _git_init(root / "b", {"composer.json": "{}"})
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)
    pulled = []
    run_pipeline(str(root), str(tmp_path / "state"), "2026-07-15", pull=True,
                 engine="semgrep", run=_empty_engine, http=lambda *a, **k: {},
                 pull_run=pulled.append)
    assert sorted(Path(p).name for p in pulled) == ["a", "b"]


def test_run_pipeline_writes_dashboard_html(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^7.4"}}'})
    state = tmp_path / "state"
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.eol, "check", _fake_eol)
    run_pipeline(str(root), str(state), "2026-07-15",
                 engine="semgrep", run=_empty_engine, http=lambda *a, **k: {})
    dash = state / "dashboard.html"
    assert dash.exists()
    assert dash.read_text().startswith("<!doctype html>")
    assert '<script id="drift-data"' in dash.read_text()

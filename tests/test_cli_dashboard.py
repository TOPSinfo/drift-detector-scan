import json
from agent import cli


def _inventory(tmp_path):
    p = tmp_path / "inventory.json"
    p.write_text(json.dumps({"generated": "2026-07-15", "repos": [
        {"path": "svc", "endpoints": [], "sdks": [], "runtimes": {}}]}))
    return p


def test_audit_out_html_writes_dashboard(tmp_path, monkeypatch):
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.osv, "query_package", lambda *a, **k: [])
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)
    inv = _inventory(tmp_path)
    out_html = tmp_path / "dashboard.html"
    rc = cli.main(["audit", "--in", str(inv), "--now", "2026-07-15",
                   "--out-html", str(out_html)])
    assert rc == 0
    assert out_html.exists() and out_html.read_text().startswith("<!doctype html>")


def test_audit_without_out_html_writes_none(tmp_path, monkeypatch):
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.osv, "query_package", lambda *a, **k: [])
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)
    inv = _inventory(tmp_path)
    cli.main(["audit", "--in", str(inv), "--now", "2026-07-15",
              ])
    assert not (tmp_path / "dashboard.html").exists()

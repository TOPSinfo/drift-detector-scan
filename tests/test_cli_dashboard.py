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


def test_audit_banner_shows_exposed_secrets_count(tmp_path, monkeypatch, capsys):
    """`counts` gained an EXPOSED bucket (Fix C); the CLI banner must show it — otherwise
    the one signal loud enough to need no network or date (a leaked credential) is the one
    thing this line never mentions."""
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.osv, "query_package", lambda *a, **k: [])
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)
    p = tmp_path / "inventory.json"
    p.write_text(json.dumps({"generated": "2026-07-15", "repos": [
        {"path": "svc", "endpoints": [], "sdks": [], "runtimes": {},
         "secrets": [{"ruleId": "generic-api-key", "path": "config/keys.php", "line": 5,
                     "commit": "deadbeef"}]}]}))
    rc = cli.main(["audit", "--in", str(p), "--now", "2026-07-15"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 exposed" in out


def test_audit_without_out_html_writes_none(tmp_path, monkeypatch):
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.osv, "query_package", lambda *a, **k: [])
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)
    inv = _inventory(tmp_path)
    cli.main(["audit", "--in", str(inv), "--now", "2026-07-15",
              ])
    assert not (tmp_path / "dashboard.html").exists()


def _full_state_dir(tmp_path):
    """A complete state dir (drift.json, inventory.json, audit.json, drift.md,
    dashboard.html, summary.html) built from the SAME pure renderers `run_pipeline` uses —
    everything `verify` requires, so this fixture stands in for a real `run`."""
    from agent.lib.dashboard_render import build_payload, build_bundle, render_payload
    from agent.lib.md_render import render_markdown
    from agent.lib.summary_render import render_summary

    now = "2026-08-13"
    inventory = {"generated": now, "repos": [{"path": "svc", "endpoints": [], "sdks": [],
                                              "runtimes": {}}]}
    audit = {"generated": now, "findings": [],
            "counts": {"DEPRECATED": 0, "REVIEW": 0, "reposAffected": 0}, "coverage": {}}
    payload = build_payload(inventory, audit)
    bundle = build_bundle(inventory, audit, now)

    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    (tmp_path / "audit.json").write_text(json.dumps(audit))
    (tmp_path / "drift.json").write_text(json.dumps(payload))
    (tmp_path / "drift.md").write_text(render_markdown(payload, now))
    (tmp_path / "dashboard.html").write_text(
        render_payload(payload, now, bundle=bundle))
    (tmp_path / "summary.html").write_text(render_summary(payload, now))
    return now


def test_render_repairs_a_state_dir_missing_summary_html(tmp_path):
    """task-5b Finding 2: `summary.html` became REQUIRED by `verify` (missing -> exit 4),
    but `render` — the obvious repair for a state dir predating this change, or one that was
    hand-staged — rewrote only dashboard.html. `verify` named the missing file correctly, yet
    the documented remedy did not produce it. A state dir missing ONLY summary.html must
    become verifiable again after `render`."""
    now = _full_state_dir(tmp_path)
    (tmp_path / "summary.html").unlink()

    # confirm the fixture is otherwise sound and the gap is real
    assert cli.main(["verify", "--state", str(tmp_path)]) == 4

    rc = cli.main(["render", "--state", str(tmp_path), "--now", now])
    assert rc == 0
    assert (tmp_path / "summary.html").exists()

    assert cli.main(["verify", "--state", str(tmp_path)]) == 0

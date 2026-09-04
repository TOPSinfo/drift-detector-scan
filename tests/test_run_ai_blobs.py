"""agent.run.run_pipeline must surface the optional AI-tier documents (leads.json, adhoc.json)
into dashboard.html as their own id'd blobs -- exactly like it already does for research.json.

This is an integration test over run_pipeline (not render_payload, which already supports the
blobs and would pass trivially either way), because the actual defect is that run.py never reads
leads.json/adhoc.json off disk and never passes them through. The harness here is lifted from
tests/test_run_pipeline.py: a real git repo scanned by an injected no-op engine, and a
monkeypatched agent.audit.eol.check so nothing touches the network.
"""
import json
import subprocess

from agent.run import run_pipeline
from tests import gitleaks_fake


def _no_secrets(args):
    return gitleaks_fake.EMPTY


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _empty_engine(args):
    return json.dumps([])


def _write_json(path, obj):
    path.write_text(json.dumps(obj))


def _run(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": "{}"})
    state = tmp_path / "state"
    state.mkdir()
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)
    return root, state


def test_run_pipeline_embeds_leads_and_adhoc_blobs_when_present(tmp_path, monkeypatch):
    """The primary guard. Before the fix, run.py only ever reads research.json and passes
    `research=` to render_payload -- leads.json/adhoc.json sitting right next to it in the state
    dir are never read, so the AI Frontier tab silently drops two of its three tiers. This must
    fail on the pre-fix code and pass after."""
    root, state = _run(tmp_path, monkeypatch)
    _write_json(state / "leads.json", {"schema": "drift-leads/v1", "repos": []})
    _write_json(state / "adhoc.json", {"schema": "drift-adhoc/v1", "claims": []})

    run_pipeline(str(root), str(state), "2026-07-15",
                 engine="semgrep", run=_empty_engine, http=lambda *a, **k: {},
                 secrets_run=_no_secrets)

    html = (state / "dashboard.html").read_text()
    assert 'id="leads-data"' in html
    assert 'id="adhoc-data"' in html


def test_run_pipeline_hides_ai_tiers_when_documents_absent(tmp_path, monkeypatch):
    """'Cannot see' != 'clean', extended to the AI tiers: no leads.json/adhoc.json in the state
    dir means no pass ran, so the tier must be HIDDEN from the dashboard, not rendered as a
    confident 0."""
    root, state = _run(tmp_path, monkeypatch)

    run_pipeline(str(root), str(state), "2026-07-15",
                 engine="semgrep", run=_empty_engine, http=lambda *a, **k: {},
                 secrets_run=_no_secrets)

    html = (state / "dashboard.html").read_text()
    assert 'id="leads-data"' not in html
    assert 'id="adhoc-data"' not in html


def test_run_pipeline_hides_ai_tier_when_document_is_corrupt(tmp_path, monkeypatch):
    """An unreadable/corrupt AI document must not fail the scan -- it just hides that tier.
    Covers the _optional() helper's except branch (invalid JSON)."""
    root, state = _run(tmp_path, monkeypatch)
    (state / "leads.json").write_text("{not valid json")
    _write_json(state / "adhoc.json", {"schema": "drift-adhoc/v1", "claims": []})

    out = run_pipeline(str(root), str(state), "2026-07-15",
                       engine="semgrep", run=_empty_engine, http=lambda *a, **k: {},
                       secrets_run=_no_secrets)

    assert out is not None                        # the scan completed, it did not raise
    html = (state / "dashboard.html").read_text()
    assert 'id="leads-data"' not in html           # corrupt document -> tier hidden
    assert 'id="adhoc-data"' in html               # the sibling, valid document is unaffected


def test_run_pipeline_hides_ai_tier_when_document_has_invalid_utf8(tmp_path, monkeypatch):
    """Invalid UTF-8 in a JSON file raises UnicodeDecodeError during json.load(), which is
    a ValueError subclass, not OSError. Before the fix, this would crash the entire scan.
    After the fix, _optional catches ValueError and hides the tier gracefully."""
    root, state = _run(tmp_path, monkeypatch)
    # Write raw invalid UTF-8 bytes (simulating a truncated write from a prior crash)
    (state / "leads.json").write_bytes(b'{"schema": "drift-leads/v1", "x": "\xff\xfe"}')
    _write_json(state / "adhoc.json", {"schema": "drift-adhoc/v1", "claims": []})

    out = run_pipeline(str(root), str(state), "2026-07-15",
                       engine="semgrep", run=_empty_engine, http=lambda *a, **k: {},
                       secrets_run=_no_secrets)

    assert out is not None                        # the scan completed, it did not raise
    html = (state / "dashboard.html").read_text()
    assert 'id="leads-data"' not in html           # invalid UTF-8 -> tier hidden
    assert 'id="adhoc-data"' in html               # the sibling, valid document is unaffected


def test_the_certified_blob_is_byte_identical_with_and_without_ai_blobs(tmp_path, monkeypatch):
    """REGRESSION NET, not a red-green guard: this pins an existing guarantee at the run_pipeline
    layer (render_payload already keeps drift-data byte-identical; kept here as an integration-
    level tripwire). Task 8 deletes the side-car renderers (INVENTORY.md/AUDIT.md/DRIFT.md-style
    surfaces) that today provide part of this separation guarantee -- this test is what keeps the
    guarantee proven once those are gone: the certified drift-data blob must not move by a single
    byte whether or not leads.json/adhoc.json exist in the state dir.
    """
    import re

    def certified(html):
        m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>', html,
                      re.S)
        return m.group(1)

    root, state_plain = _run(tmp_path, monkeypatch)
    run_pipeline(str(root), str(state_plain), "2026-07-15",
                 engine="semgrep", run=_empty_engine, http=lambda *a, **k: {},
                 secrets_run=_no_secrets)
    plain = (state_plain / "dashboard.html").read_text()

    state_ai = tmp_path / "state-ai"
    state_ai.mkdir()
    _write_json(state_ai / "leads.json", {"schema": "drift-leads/v1", "repos": []})
    _write_json(state_ai / "adhoc.json", {"schema": "drift-adhoc/v1", "claims": []})
    run_pipeline(str(root), str(state_ai), "2026-07-15",
                 engine="semgrep", run=_empty_engine, http=lambda *a, **k: {},
                 secrets_run=_no_secrets)
    withai = (state_ai / "dashboard.html").read_text()

    assert certified(plain) == certified(withai)

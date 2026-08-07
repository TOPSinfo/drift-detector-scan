"""The pre-scan scope gate — pure assess/render, deterministic, no I/O."""
from agent.lib import probe


def _facts(**over):
    f = {
        "host": "git.x",
        "projects": [("/a", "grp/repo", "local-git")],
        "errors": [],
        "repos": [{"name": "grp/repo", "verdict": "KNOWN"}],
        "edges": [],
        "unmodeledLangs": {},
        "languageSignal": {"php": True},
        "accept": [],
    }
    f.update(over)
    return f


def test_clean_scope_exits_zero():
    r = probe.assess(_facts())
    assert r["exit_code"] == probe.CLEAN
    assert "scope clean" in r["text"]


def test_nothing_resolves_exits_four():
    r = probe.assess(_facts(projects=[], repos=[],
                            errors=[{"root": "https://git.x/grp/gone", "reason": "404"}]))
    assert r["exit_code"] == probe.NOTHING


def test_unreachable_source_is_an_open_hole_and_trips_the_gate():
    r = probe.assess(_facts(errors=[{"root": "https://git.x/grp/ebayapinew.git",
                                     "reason": "404"}]))
    assert r["exit_code"] == probe.GATE_TRIPPED
    assert any(h["gap"] == "repo:ebayapinew" and not h["accepted"] for h in r["holes"])


def test_missing_private_dep_trips_the_gate_with_a_dep_gap_id():
    edges = [{"repo": "marketplacehub", "present": [],
              "missing": [{"url": "https://git.x/akshit/catchapi.git",
                           "id": "git.x/akshit/catchapi"}]}]
    r = probe.assess(_facts(edges=edges))
    assert r["exit_code"] == probe.GATE_TRIPPED
    assert any(h["gap"] == "dep:git.x/akshit/catchapi" for h in r["holes"])
    assert "MISSING : git.x/akshit/catchapi" in r["text"]


def test_unmodeled_language_trips_the_gate():
    r = probe.assess(_facts(unmodeledLangs={"javascript": ["grp/repo"]},
                            languageSignal={"php": True, "javascript": False}))
    assert r["exit_code"] == probe.GATE_TRIPPED
    assert any(h["gap"] == "lang:javascript" for h in r["holes"])
    assert "javascript ✗no-egress-rules" in r["text"]


def test_accepted_hole_is_acknowledged_not_open():
    r = probe.assess(_facts(
        errors=[{"root": "https://git.x/grp/ebayapinew", "reason": "404"}],
        accept=[{"gap": "repo:ebayapinew", "reason": "decommissioned next sprint"}]))
    assert r["exit_code"] == probe.CLEAN               # acknowledged → no longer trips
    h = next(h for h in r["holes"] if h["gap"] == "repo:ebayapinew")
    assert h["accepted"] and "decommissioned" in h["reason"]
    assert "ACCEPTED: decommissioned next sprint" in r["text"]
    assert "structural or acknowledged" in r["text"]


def test_edges_show_present_and_missing_split():
    edges = [{"repo": "marketplacehub",
              "present": [{"url": "u1", "id": "git.x/example-org/amazonspapi"}],
              "missing": [{"url": "u2", "id": "git.x/example-org/neto"}]}]
    r = probe.assess(_facts(edges=edges))
    assert "✓ in fleet: git.x/example-org/amazonspapi" in r["text"]
    assert "✗ MISSING : git.x/example-org/neto" in r["text"]


def test_render_is_byte_identical():
    assert probe.assess(_facts())["text"] == probe.assess(_facts())["text"]


# --- CLI wiring: resolve → census → edges → gate, end to end on a temp repo ---
def test_cli_probe_trips_gate_on_a_private_dep(tmp_path, capsys):
    import subprocess
    from agent import cli
    repo = tmp_path / "app"
    repo.mkdir()
    (repo / "composer.json").write_text(
        '{"require": {"php": "^8.1", "acme/wrapper": "dev-main"},'
        ' "repositories": [{"type": "vcs", "url": "https://git.x/acme/wrapper.git"}]}')
    (repo / "index.php").write_text("<?php echo 1;")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, check=True)
    state = tmp_path / "state"
    code = cli.main(["probe", "--root", str(repo), "--state", str(state)])
    out = capsys.readouterr().out
    assert code == probe.GATE_TRIPPED
    assert "dep:git.x/acme/wrapper" in out          # the private dep, not in fleet
    assert "MISSING : git.x/acme/wrapper" in out


def test_markdown_summary_has_scope_table_covered_and_blind():
    edges = [{"repo": "marketplacehub",
              "present": [{"url": "u", "id": "git.x/example-org/amazonspapi"}],
              "missing": [{"url": "u2", "id": "git.x/example-org/neto"}]}]
    r = probe.assess(_facts(edges=edges))
    md = r["markdown"]
    assert "## Drift probe" in md
    assert "| Repo | Covered (in fleet) | Blind (not in fleet) |" in md
    assert "| marketplacehub | amazonspapi | neto |" in md          # short names in the table
    assert "1 repo(s) in scope" in md and "KNOWN" in md


def test_markdown_lists_open_holes_with_gap_ids():
    r = probe.assess(_facts(unmodeledLangs={"javascript": ["a"]},
                            languageSignal={"php": True, "javascript": False}))
    assert "`lang:javascript`" in r["markdown"] and "**OPEN**" in r["markdown"]

"""The drift-ops persistence-repo template (config + overlay + state). The scan runs on
GitHub Actions (see test_github_scan_workflow); this guards the data-repo structure."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent / "deploy" / "drift-ops"


def test_drift_yml_template_is_a_valid_config():
    from agent.lib import ops_config
    cfg = ops_config.load(str(ROOT / "config" / "drift.yml"))     # must parse + validate
    assert cfg["fleet"] and cfg["host"] == "git.example.com"      # placeholder, not a client host
    assert cfg["delivery"]["mode"] == "dry-run"                   # safe default in the template


def test_clones_and_cache_are_gitignored_but_reports_are_not():
    ign = (ROOT / ".gitignore").read_text()
    assert "state/sources/" in ign and "state/repos_v" in ign
    assert "drift.json" not in ign                      # reports ARE committed


def test_overlay_and_state_dirs_exist():
    assert (ROOT / "catalog").is_dir() and (ROOT / "state").is_dir()


def test_no_token_is_committed_in_the_template():
    for p in ROOT.rglob("*"):
        if p.is_file():
            assert not re.search(r"glpat-[A-Za-z0-9_-]{15,}", p.read_text(errors="ignore"))

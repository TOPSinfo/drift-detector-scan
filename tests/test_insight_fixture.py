"""End-to-end regression lock: a committed, public-safe SYNTHETIC 2-repo PHP fixture proving the
concat idiom (`getHost() . $resource_path`) attributes across TWO different vendors (idiom, not
vendor-specific), and that sinks + bare path-literals surface as residue when unattributed.

Runs the REAL opengrep/semgrep engine over the fixture (hermetic — the engine reads files, never
executes them; no network). Engine resolution mirrors tests/test_opengrep_live.py's approach.
"""
import os
import sys
import shutil
from pathlib import Path

import pytest

from agent.lib.vendor_rules import write_ruleset
from agent.lib.engine import run_scan
from agent.lib.endpoints import scan_endpoints
from agent.lib.vendors import load_vendors

FIX = Path(__file__).parent / "fixtures" / "insight"


def _find_engine():
    from agent.lib.scan_util import resolve_engine
    try:
        return resolve_engine()          # prefers ast-grep, falls back to opengrep/semgrep
    except RuntimeError:
        return None


_ENGINE = _find_engine()


def _scan(repo_dir, vendors, tmp_path):
    rules = tmp_path / "rules.yaml"
    write_ruleset(vendors, str(rules))
    res = run_scan(str(repo_dir), str(rules), engine=_ENGINE)
    return scan_endpoints(res["matches"], str(repo_dir), vendors)


@pytest.mark.skipif(_ENGINE is None, reason="no scan engine installed")
def test_repo_a_attributes_sp_api_and_reports_residue(tmp_path):
    vendors = load_vendors()
    out = _scan(FIX / "repo_a", vendors, tmp_path)

    vers = {e.get("version") for e in out["endpoints"] if e["techKey"] == "api:amazon-sp-api"}
    assert "2026-01-01" in vers                                   # concat path attributed to SP-API

    samples = {p["sample"] for p in out["residue"]["pathLiterals"]}
    assert "/feeds/2021-06-30/documents" in samples               # Const.php literal = residue (no assembly)

    assert any("Client.php" in s["loc"] for s in out["residue"]["sinks"])   # curl_exec = sink residue


@pytest.mark.skipif(_ENGINE is None, reason="no scan engine installed")
def test_repo_b_attributes_stripe_proving_idiom_not_vendor(tmp_path):
    vendors = load_vendors()
    out = _scan(FIX / "repo_b", vendors, tmp_path)

    stripe = [e for e in out["endpoints"] if e["techKey"] == "api:stripe" and e.get("version") == "v1"]
    assert stripe                                                  # SAME idiom, different vendor

    assert out["residue"]["pathLiterals"] == []                    # all attributed -> clean

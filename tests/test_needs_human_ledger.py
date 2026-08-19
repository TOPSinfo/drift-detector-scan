"""An honest `unknown` must survive the next scan.

The resolution gate always accepted a fourth verdict — `unknown`, "I looked and could not
tell" — precisely so nobody is pressured into inventing an own-domain or a vendor. But
`apply()` returned it in an ephemeral summary dict and persisted nothing, and no code path
could ever emit `needs-human`, so the SECOND deterministic scan re-derived those hosts
straight back to `queued`.

The cost is the distinction principle 1 exists to protect: "the pass ran and could not tell"
became indistinguishable from "nobody has looked yet". On the live three-repo state that read
as `resolutionRan: True` with `queued: 8, needs-human: 0`.

Client hostnames, so overlay-only — never a package YAML.
"""
import json
import os

import pytest
import yaml

from agent import resolve
from agent.lib import catalog_overlay, dashboard_render


@pytest.fixture()
def overlay(tmp_path, monkeypatch):
    d = tmp_path / "catalog"
    d.mkdir()
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(d))
    return d


def _unknown(host="www.example-shipper.com", repo="example-org/inventory-app", note="page said only 'Welcome'"):
    return {"status": "unknown", "host": host, "repo": repo, "note": note}


def _inv(host="www.example-shipper.com", repo="example-org/inventory-app"):
    return {"generated": "2026-08-15",
            "repos": [{"path": repo, "endpoints": [
                {"vendor": "Unknown external", "domain": host, "version": None,
                 "hostClass": "api-lead", "classified": False, "files": [f"{repo}.php:1"]}]}]}


def test_an_unknown_verdict_is_written_to_the_ledger(overlay):
    """It used to be returned and dropped. A verdict nobody records is a verdict nobody made."""
    out = resolve.apply([_unknown()], now="2026-08-15")
    assert out["written"]["needs_human"] == 1
    path = overlay / catalog_overlay.NEEDS_HUMAN
    assert path.is_file(), f"no ledger written; overlay holds {os.listdir(overlay)}"
    entries = yaml.safe_load(path.read_text())
    assert len(entries) == 1
    e = entries[0]
    assert e["host"] == "www.example-shipper.com" and e["repo"] == "example-org/inventory-app"
    assert e["checked"] == "2026-08-15" and e["by"] == "ai-resolution"
    assert "Welcome" in e["note"]


def test_a_recorded_host_derives_as_needs_human_not_queued(overlay):
    """The whole point: the next deterministic scan must re-derive the recorded verdict."""
    resolve.apply([_unknown()], now="2026-08-15")
    eps = dashboard_render._endpoints_of(_inv())
    assert [e["coverage"] for e in eps] == ["needs-human"], eps


def test_without_a_ledger_entry_the_same_host_stays_queued(overlay):
    """The control. If this ever goes green on its own, the ledger is inventing coverage —
    an unlooked-at host must keep showing up as unresolved work."""
    eps = dashboard_render._endpoints_of(_inv())
    assert [e["coverage"] for e in eps] == ["queued"], eps


def test_the_ledger_is_scoped_to_the_repo_that_recorded_it(overlay):
    """Two clients can share one overlay dir. An unknown recorded against one repo must not
    silently settle the same host somewhere else."""
    resolve.apply([_unknown(repo="example-org/inventory-app")], now="2026-08-15")
    other = dashboard_render._endpoints_of(_inv(repo="some-other-repo"))
    assert [e["coverage"] for e in other] == ["queued"], other


def test_unknown_writes_nothing_to_the_other_catalogs(overlay):
    """`unknown` is the honest non-answer: it must never leak into vendors, own-domains or
    sunsets, where it would become an assertion about the world."""
    resolve.apply([_unknown()], now="2026-08-15")
    for name in (catalog_overlay.VENDORS, catalog_overlay.OWN_DOMAINS, catalog_overlay.SUNSETS):
        assert not (overlay / name).exists(), f"unknown leaked into {name}"


def test_re_recording_the_same_unknown_does_not_duplicate(overlay):
    resolve.apply([_unknown()], now="2026-08-15")
    resolve.apply([_unknown(note="second look, still nothing")], now="2026-08-16")
    entries = yaml.safe_load((overlay / catalog_overlay.NEEDS_HUMAN).read_text())
    assert len(entries) == 1, entries


def test_a_tracked_host_is_not_downgraded_by_a_stale_ledger_entry(overlay):
    """needs-human only ever replaces `queued`. If the host later becomes a catalogued vendor,
    tracked wins — the ledger records that nobody could tell, not that nobody may ever."""
    resolve.apply([_unknown(host="api.epgparcels.com")], now="2026-08-15")
    inv = _inv(host="api.epgparcels.com")
    inv["repos"][0]["endpoints"][0].update({"classified": True, "vendor": "ePost Global",
                                            "hostClass": "api"})
    assert [e["coverage"] for e in dashboard_render._endpoints_of(inv)] == ["tracked"]

"""The `clean` command: a single cleanup that finds scattered run outputs via the run ledger,
preserves the absorbed catalog by default, and refuses to touch a path that isn't ours."""
import json
import os

import pytest

from agent.lib import cleanup


@pytest.fixture()
def home(tmp_path, monkeypatch):
    # DRIFT_HOME redirects ~/.drift so no test writes to the real home (drift_home honors it).
    h = tmp_path / "drifthome"
    monkeypatch.setenv("DRIFT_HOME", str(h))
    return h


def _state(dir_path):
    os.makedirs(dir_path, exist_ok=True)
    with open(os.path.join(dir_path, "inventory.json"), "w") as fh:
        fh.write("{}")
    return str(dir_path)


def test_record_run_is_deduped(home, tmp_path):
    s = _state(tmp_path / "proj" / ".drift-detector")
    cleanup.record_run(s)
    cleanup.record_run(s)                                   # second call must not duplicate
    assert cleanup.read_runs() == [os.path.abspath(s)]


def test_all_removes_recorded_runs_but_keeps_catalog(home, tmp_path):
    # two scattered run dirs recorded in the ledger + an absorbed catalog
    a = _state(tmp_path / "a" / ".drift-detector")
    b = _state(tmp_path / "b" / ".drift-detector")
    cleanup.record_run(a)
    cleanup.record_run(b)
    catalog = home / "catalog"
    os.makedirs(catalog, exist_ok=True)
    (catalog / "idioms.local.yaml").write_text("[]")

    pl = cleanup.plan(all_=True, state=None, include_catalog=False)
    target_paths = {t["path"] for t in pl["targets"]}
    assert os.path.abspath(a) in target_paths and os.path.abspath(b) in target_paths
    # the absorbed catalog is PRESERVED, not deleted, unless --catalog
    assert os.path.abspath(str(catalog)) not in target_paths
    assert any(p["path"] == os.path.abspath(str(catalog)) for p in pl["preserved"])

    cleanup.execute(pl["targets"])
    assert not os.path.isdir(a) and not os.path.isdir(b)   # run dirs gone
    assert os.path.isdir(catalog)                          # catalog survives
    assert cleanup.read_runs() == []                       # ledger pruned


def test_catalog_flag_removes_catalog(home, tmp_path):
    catalog = home / "catalog"
    os.makedirs(catalog, exist_ok=True)
    (catalog / "x.yaml").write_text("[]")
    pl = cleanup.plan(all_=True, state=None, include_catalog=True)
    assert any(t["kind"] == "catalog" for t in pl["targets"])


def test_guardrail_refuses_a_non_drift_dir(home, tmp_path):
    # a random folder that is NOT a drift state dir must not be classified as removable
    victim = tmp_path / "my-important-code"
    victim.mkdir()
    (victim / "main.py").write_text("print('hi')")
    assert cleanup.is_state_dir(str(victim)) is False
    # planning a single --state on it yields no targets (the CLI turns this into a refusal)
    pl = cleanup.plan(all_=False, state=str(victim), include_catalog=False)
    assert pl["targets"] == []
    assert victim.exists()                                  # untouched


def test_state_dir_recognized_by_marker_or_name(home, tmp_path):
    by_marker = _state(tmp_path / "x")                      # has inventory.json
    by_name = tmp_path / "y" / ".drift-detector"            # named .drift-detector, empty
    by_name.mkdir(parents=True)
    assert cleanup.is_state_dir(by_marker) is True
    assert cleanup.is_state_dir(str(by_name)) is True


def test_report_plan_counts_without_deleting(home, tmp_path):
    a = _state(tmp_path / "a" / ".drift-detector")
    cleanup.record_run(a)
    pl = cleanup.plan(all_=True, state=None, include_catalog=False)
    assert len(pl["targets"]) == 1 and pl["total"] >= 0
    assert os.path.isdir(a)                                 # report/plan never deletes


def test_ledger_entry_that_no_longer_exists_is_skipped(home, tmp_path):
    gone = str(tmp_path / "deleted" / ".drift-detector")
    cleanup.record_run(gone)                                # recorded, but never created on disk
    pl = cleanup.plan(all_=True, state=None, include_catalog=False)
    assert pl["targets"] == []                              # a stale ledger entry is simply skipped

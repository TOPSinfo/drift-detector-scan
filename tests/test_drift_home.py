"""~/.drift is the one home for eval + central-run artifacts (Phase 0). The in-place
<folder>/.drift-detector behavior is unchanged — this only adds the central home."""
import os
from agent.lib import drift_home


def test_drift_root_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path / "custom"))
    assert drift_home.drift_root() == str(tmp_path / "custom")
    assert os.path.isdir(drift_home.drift_root())          # created on demand


def test_drift_root_defaults_under_home(monkeypatch):
    monkeypatch.delenv("DRIFT_HOME", raising=False)
    assert drift_home.drift_root() == os.path.join(os.path.expanduser("~"), ".drift")


def test_reports_and_eval_subpaths(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path))
    assert drift_home.reports_home("fleet") == os.path.join(str(tmp_path), "reports", "fleet")
    assert drift_home.eval_home() == os.path.join(str(tmp_path), "eval")
    assert os.path.isdir(drift_home.reports_home("fleet"))   # subdir created
    assert os.path.isdir(drift_home.eval_home())

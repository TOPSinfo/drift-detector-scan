from agent.cli import main


def test_engine_threads_defaults_to_none_so_ast_grep_keeps_its_own_default(monkeypatch):
    """Unset --engine-threads must reach run_pipeline as None — ast-grep's own default
    (every logical CPU for one invocation) is unchanged unless a caller opts in."""
    captured = {}

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured["engine_threads"] = kwargs.get("engine_threads")
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 0
    assert captured["engine_threads"] is None


def test_engine_threads_flows_through_to_run_pipeline(monkeypatch):
    """A repo report caught live (2026-09-07): a single ast-grep invocation defaults to
    using every logical CPU on the machine for its own internal parallelism, independent of
    --jobs (repos scanned concurrently) — enough on its own to exhaust memory on a small CI
    runner scanning a large repo. --engine-threads is the knob that caps THAT."""
    captured = {}

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured["engine_threads"] = kwargs.get("engine_threads")
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25",
               "--engine-threads", "2"])
    assert rc == 0
    assert captured["engine_threads"] == 2


def test_inventory_scan_engine_threads_flows_through(tmp_path, monkeypatch):
    import agent.inventory_scan as inv
    captured = {}

    def fake_scan_folder(root, state, now, **kwargs):
        captured["engine_threads"] = kwargs.get("engine_threads")
        return {"doc": {"repos": [], "coverage": {"reposErrored": []}}, "diff": {}}

    monkeypatch.setattr(inv, "scan_folder", fake_scan_folder)
    rc = main(["inventory-scan", "--root", ".", "--state", str(tmp_path),
               "--out-json", str(tmp_path / "inv.json"), "--now", "2026-08-25",
               "--engine-threads", "3"])
    assert rc == 0
    assert captured["engine_threads"] == 3


def test_run_rejects_a_jobs_value_below_one(capsys):
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25", "--jobs", "0"])
    assert rc == 2
    assert "--jobs" in capsys.readouterr().err


def test_jobs_flag_omitted_parses_to_none_so_config_can_supply_it():
    """argparse's raw default must be None, not 1 — only that lets scan.jobs in --config
    take effect. (The effective-default-is-1 behaviour is covered by the test below.)"""
    import argparse

    from agent import cli
    parser_holder = {}

    real = argparse.ArgumentParser.parse_args

    def capture(self, argv=None):
        args = real(self, argv)
        parser_holder["args"] = args
        return args

    argparse.ArgumentParser.parse_args = capture
    try:
        try:
            cli.main(["run", "--state", "/tmp/x", "--now", "2026-08-25"])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = real

    assert getattr(parser_holder["args"], "jobs", "MISSING") is None


def test_jobs_defaults_to_one_so_ci_behaviour_is_unchanged(monkeypatch):
    """CI passes no --jobs. The effective default must be the serial path, not CPU count."""
    captured = {}

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured["jobs"] = kwargs.get("jobs")
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 0
    assert captured["jobs"] == 1


def test_jobs_above_cpu_count_is_clamped_with_notice(monkeypatch, capsys):
    """A code review found that ast-grep is itself internally parallel, so --jobs N
    oversubscribes the CPU and can push a repo past the engine's 600s timeout — a repo that
    scans cleanly at --jobs 1 can be reported errored at a large --jobs on a loaded machine.
    The fix: cap the requested value to the CPU count, and say so on stderr rather than
    silently ignoring what the user asked for.
    """
    captured = {}

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured["jobs"] = kwargs.get("jobs")
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("os.cpu_count", lambda: 4)

    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25", "--jobs", "999"])

    assert rc == 0
    assert captured["jobs"] == 4
    err = capsys.readouterr().err
    assert "--jobs" in err
    assert "cap" in err.lower()


def test_the_cap_notice_names_the_command_that_is_actually_running(tmp_path, monkeypatch, capsys):
    """The notice hardcoded a "run: " prefix, so `inventory-scan --jobs 999` printed a
    message about a subcommand the user had not typed."""
    import agent.inventory_scan as inv

    monkeypatch.setattr("os.cpu_count", lambda: 4)
    captured = {}

    def fake_scan_folder(root, state, now, **kwargs):
        captured["jobs"] = kwargs.get("jobs")
        return {"doc": {"repos": [], "coverage": {"reposErrored": []}}, "diff": {}}

    monkeypatch.setattr(inv, "scan_folder", fake_scan_folder)

    rc = main(["inventory-scan", "--root", ".", "--state", str(tmp_path),
               "--out-json", str(tmp_path / "inv.json"), "--now", "2026-08-25",
               "--jobs", "999"])
    assert rc == 0 and captured["jobs"] == 4
    err = capsys.readouterr().err
    assert err.startswith("inventory-scan: --jobs 999 capped"), err
    assert not err.startswith("run:")


# --------------------------------------------------------------------- --only

def test_only_defaults_to_none_so_everything_is_scanned(monkeypatch):
    captured = {}

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured["categories"] = kwargs.get("categories")
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 0
    assert captured["categories"] is None


def test_only_flows_through_to_run_pipeline_as_a_frozenset(monkeypatch):
    captured = {}

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured["categories"] = kwargs.get("categories")
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25",
               "--only", "secrets,cve"])
    assert rc == 0
    assert captured["categories"] == frozenset({"secrets", "cve"})


def test_only_rejects_an_unknown_category_before_scanning_anything(monkeypatch, capsys):
    calls = {"n": 0}

    def fake_run_pipeline(*a, **k):
        calls["n"] += 1
        return {"scope": {"reposScanned": 1}}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25",
               "--only", "secrets,typo"])
    assert rc == 2
    assert calls["n"] == 0, "an invalid --only must refuse before touching anything"
    err = capsys.readouterr().err
    assert "--only" in err and "typo" in err


def test_inventory_scan_only_flows_through(tmp_path, monkeypatch):
    import agent.inventory_scan as inv
    captured = {}

    def fake_scan_folder(root, state, now, **kwargs):
        captured["categories"] = kwargs.get("categories")
        return {"doc": {"repos": [], "coverage": {"reposErrored": []}}, "diff": {}}

    monkeypatch.setattr(inv, "scan_folder", fake_scan_folder)
    rc = main(["inventory-scan", "--root", ".", "--state", str(tmp_path),
               "--out-json", str(tmp_path / "inv.json"), "--now", "2026-08-25",
               "--only", "sunsets"])
    assert rc == 0
    assert captured["categories"] == frozenset({"sunsets"})


def test_only_falls_back_to_the_config_files_scan_only_when_the_flag_is_omitted(
        tmp_path, monkeypatch):
    """scan.only in drift.yml is a persistent, declarative alternative to remembering --only
    on every invocation. Omitting the CLI flag must fall back to it."""
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  only: [secrets]\n")
    captured = {}

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured["categories"] = kwargs.get("categories")
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 0
    assert captured["categories"] == frozenset({"secrets"})


def test_only_flag_overrides_the_config_files_scan_only(tmp_path, monkeypatch):
    """An explicit --only always wins over the config file — the operator typed it on
    purpose for THIS run."""
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  only: [secrets]\n")
    captured = {}

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured["categories"] = kwargs.get("categories")
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25",
               "--only", "sunsets"])
    assert rc == 0
    assert captured["categories"] == frozenset({"sunsets"})


def _fake_run_pipeline_capturing(captured):
    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        captured.update(kwargs)
        return {"scope": {"reposScanned": 1}, "auditCounts": {}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}
    return fake_run_pipeline


def test_jobs_falls_back_to_the_config_files_scan_jobs_when_the_flag_is_omitted(
        tmp_path, monkeypatch):
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  jobs: 4\n")
    captured = {}
    monkeypatch.setattr("agent.run.run_pipeline", _fake_run_pipeline_capturing(captured))
    monkeypatch.setattr("agent.cli._capped_jobs", lambda n, cmd: n)
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 0
    assert captured["jobs"] == 4


def test_jobs_flag_overrides_the_config_files_scan_jobs(tmp_path, monkeypatch):
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  jobs: 4\n")
    captured = {}
    monkeypatch.setattr("agent.run.run_pipeline", _fake_run_pipeline_capturing(captured))
    monkeypatch.setattr("agent.cli._capped_jobs", lambda n, cmd: n)
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25",
               "--jobs", "2"])
    assert rc == 0
    assert captured["jobs"] == 2


def test_engine_threads_falls_back_to_the_config_files_scan_engine_threads(tmp_path, monkeypatch):
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  engine_threads: 3\n")
    captured = {}
    monkeypatch.setattr("agent.run.run_pipeline", _fake_run_pipeline_capturing(captured))
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 0
    assert captured["engine_threads"] == 3


def test_engine_threads_flag_overrides_the_config_files_scan_engine_threads(tmp_path, monkeypatch):
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  engine_threads: 3\n")
    captured = {}
    monkeypatch.setattr("agent.run.run_pipeline", _fake_run_pipeline_capturing(captured))
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25",
               "--engine-threads", "1"])
    assert rc == 0
    assert captured["engine_threads"] == 1


def test_pull_is_enabled_by_the_config_files_scan_pull_even_without_the_flag(
        tmp_path, monkeypatch):
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  pull: true\n")
    captured = {}
    monkeypatch.setattr("agent.run.run_pipeline", _fake_run_pipeline_capturing(captured))
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 0
    assert captured["pull"] is True


def test_pull_flag_works_even_when_config_omits_scan_pull(tmp_path, monkeypatch):
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\n")
    captured = {}
    monkeypatch.setattr("agent.run.run_pipeline", _fake_run_pipeline_capturing(captured))
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25",
               "--pull"])
    assert rc == 0
    assert captured["pull"] is True


def test_fail_on_deprecated_is_enabled_by_config_without_the_flag(tmp_path, monkeypatch, capsys):
    """scan.fail_on_deprecated: true in drift.yml must gate the build even though the CI
    invocation passes no --fail-on-deprecated — the whole point of a persistent config default."""
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  fail_on_deprecated: true\n")

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        return {"scope": {"reposScanned": 1}, "auditCounts": {"DEPRECATED": 1}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 3
    assert "gate" in capsys.readouterr().err


def test_fail_on_exposed_is_enabled_by_config_without_the_flag(tmp_path, monkeypatch, capsys):
    cfg_path = tmp_path / "drift.yml"
    cfg_path.write_text("fleet: [https://git.x/g/a]\nscan:\n  fail_on_exposed: true\n")

    def fake_run_pipeline(roots, state_dir, now, **kwargs):
        return {"scope": {"reposScanned": 1}, "auditCounts": {"EXPOSED": 1}, "counts": {},
                "coverage": {}, "rootsUnscannable": [], "resolve": None}

    monkeypatch.setattr("agent.run.run_pipeline", fake_run_pipeline)
    rc = main(["run", "--config", str(cfg_path), "--state", "/tmp/x", "--now", "2026-08-25"])
    assert rc == 7
    assert "gate" in capsys.readouterr().err

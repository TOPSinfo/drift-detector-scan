from agent.cli import main


def test_run_rejects_a_jobs_value_below_one(capsys):
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25", "--jobs", "0"])
    assert rc == 2
    assert "--jobs" in capsys.readouterr().err


def test_jobs_defaults_to_one_so_ci_behaviour_is_unchanged():
    """CI passes no --jobs. The default must be the serial path, not CPU count."""
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

    assert getattr(parser_holder["args"], "jobs", None) == 1


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

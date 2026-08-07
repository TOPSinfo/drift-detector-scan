from agent.lib import schedule


class FakeCrontab:
    """In-memory stand-in for the crontab command."""
    def __init__(self, initial=""):
        self.content = initial

    def __call__(self, action, content=None):
        if action == "read":
            return self.content
        self.content = content or ""
        return ""


def test_install_writes_wrapper_and_one_marked_line(tmp_path):
    state = tmp_path / "state"
    ct = FakeCrontab(initial="0 0 * * * echo existing\n")
    line = schedule.install_cron(str(tmp_path / "repos"), str(state), "0 7 * * 0",
                                 plugin_root="/plug",
                                 path_env="/usr/bin:/home/u/.local/bin", crontab_run=ct)
    # wrapper script (values are shlex-quoted; safe strings render unquoted)
    wrapper = state / "cron-run.sh"
    body = wrapper.read_text()
    assert "/plug/bin/drift-scan" in body and "run --root" in body
    assert "export PATH=" in body and "/usr/bin:/home/u/.local/bin" in body
    assert wrapper.stat().st_mode & 0o100                       # executable
    # crontab: existing line preserved + one marked line added
    assert "echo existing" in ct.content
    assert ct.content.count("# drift-detector:") == 1
    assert line in ct.content and line.startswith("0 7 * * 0")
    # config persisted
    cfg = schedule.load_config(str(state))
    assert cfg["schedule"] == "0 7 * * 0" and "connectors" not in cfg   # chat stripped on hybrid


def test_reinstall_is_idempotent(tmp_path):
    state = str(tmp_path / "state")
    ct = FakeCrontab()
    schedule.install_cron(str(tmp_path / "r"), state, "0 7 * * 0", plugin_root="/p", crontab_run=ct)
    schedule.install_cron(str(tmp_path / "r"), state, "30 6 * * 1", plugin_root="/p", crontab_run=ct)
    assert ct.content.count("# drift-detector:") == 1           # replaced, not duplicated
    assert "30 6 * * 1" in ct.content and "0 7 * * 0" not in ct.content


def test_unschedule_removes_only_this_folders_line(tmp_path):
    state_a = str(tmp_path / "a")
    state_b = str(tmp_path / "b")
    ct = FakeCrontab(initial="0 0 * * * keep-me\n")
    schedule.install_cron(str(tmp_path / "ra"), state_a, "0 7 * * 0", plugin_root="/p", crontab_run=ct)
    schedule.install_cron(str(tmp_path / "rb"), state_b, "0 8 * * 0", plugin_root="/p", crontab_run=ct)
    assert ct.content.count("# drift-detector:") == 2

    removed = schedule.remove_cron(state_a, crontab_run=ct)
    assert removed is True
    assert ct.content.count("# drift-detector:") == 1           # only b's line remains
    assert "keep-me" in ct.content                              # unrelated line untouched
    assert schedule.remove_cron(state_a, crontab_run=ct) is False   # already gone


def test_install_aborts_on_ambiguous_crontab_read_failure(tmp_path):
    # a read failure that is NOT "no crontab" must abort, never overwrite the real crontab
    import subprocess as sp
    from agent.lib import schedule as sched

    def read_boom(cmd, capture_output=True, text=True, **kw):
        if cmd[:2] == ["crontab", "-l"]:
            return sp.CompletedProcess(cmd, 1, stdout="", stderr="crontab: permission denied")
        raise AssertionError("must not reach the write step")

    import pytest
    monkey = pytest.MonkeyPatch()
    monkey.setattr(sched.subprocess, "run", read_boom)
    try:
        with pytest.raises(RuntimeError, match="overwriting"):
            sched.install_cron(str(tmp_path / "r"), str(tmp_path / "s"), "0 7 * * 0", plugin_root="/p")
    finally:
        monkey.undo()


def test_shlex_quotes_path_with_spaces(tmp_path):
    import os
    import shlex
    ct = FakeCrontab()
    state = tmp_path / "sp ace"
    schedule.install_cron(str(tmp_path / "re po"), str(state), "0 7 * * 0",
                          plugin_root="/p", crontab_run=ct)
    body = (state / "cron-run.sh").read_text()
    # the space-containing root is safely quoted (no bare `--root .../re po` that cron would split)
    assert shlex.quote(os.path.abspath(str(tmp_path / "re po"))) in body


def test_wrapper_runs_catalog_check_for_weekly_freshness(tmp_path):
    """The weekly cron re-checks vendor sources against the catalog, so a new/moved
    retirement surfaces without anyone remembering to run it by hand."""
    from agent.lib import schedule
    state = tmp_path / "s"; state.mkdir()
    schedule.install_cron(str(tmp_path / "r"), str(state), "0 7 * * 0", plugin_root="/plug",
                          crontab_run=lambda *a: "")
    body = (state / "cron-run.sh").read_text()
    assert "catalog-check --now" in body
    assert "catalog-check.log" in body
    assert "|| true" in body                     # freshness is non-fatal to the scan job


def test_wrapper_freshness_step_is_non_fatal_and_isolated(tmp_path):
    """Simulate a run: a fake runner whose catalog-check exits 3 (changes found) must NOT
    fail the wrapper, and writes its own log."""
    import subprocess, os, stat
    from agent.lib import schedule
    state = tmp_path / "s"; state.mkdir()
    # a fake drift-scan: `run` succeeds, `catalog-check` exits 3
    fake_root = tmp_path / "plug"; (fake_root / "bin").mkdir(parents=True)
    fake = fake_root / "bin" / "drift-scan"
    fake.write_text('#!/usr/bin/env bash\n'
                    'if [ "$1" = "catalog-check" ]; then echo "2 changes"; exit 3; fi\n'
                    'echo "scan ok"; exit 0\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    schedule.install_cron(str(tmp_path / "r"), str(state), "0 7 * * 0",
                          plugin_root=str(fake_root), crontab_run=lambda *a: "")
    # run the wrapper (no installed_plugins.json here -> falls back to the pinned fake)
    rc = subprocess.run(["bash", str(state / "cron-run.sh")],
                        env={**os.environ, "HOME": str(tmp_path)}).returncode
    assert rc == 0, "catalog-check exit 3 must not fail the scheduled scan job"
    assert (state / "catalog-check.log").read_text().strip() == "2 changes"

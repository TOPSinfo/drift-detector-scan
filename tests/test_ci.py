from agent import cli


def _run_args(tmp_path, *extra):
    return ["run", "--root", str(tmp_path), "--state", str(tmp_path / "s"),
            "--now", "2026-07-15", *extra]


def test_fail_on_deprecated_exit_code(monkeypatch, tmp_path):
    import agent.run as run_mod

    def counts(dep, rev=0):
        return lambda *a, **k: {"scope": {"reposScanned": 1}, "auditCounts": {"DEPRECATED": dep, "REVIEW": rev}, "delivered": []}

    monkeypatch.setattr(run_mod, "run_pipeline", counts(2))
    assert cli.main(_run_args(tmp_path, "--fail-on-deprecated")) == 3      # gate trips

    monkeypatch.setattr(run_mod, "run_pipeline", counts(0, 3))
    assert cli.main(_run_args(tmp_path, "--fail-on-deprecated")) == 0      # only REVIEW -> passes

    monkeypatch.setattr(run_mod, "run_pipeline", counts(5))
    assert cli.main(_run_args(tmp_path)) == 0                              # no flag -> never fails


def test_fail_on_deprecated_does_not_gate_on_exposed_secrets_but_says_so(monkeypatch, tmp_path, capsys):
    """Whether --fail-on-deprecated should ALSO fail on EXPOSED secrets is a deliberate,
    separate policy decision (out of scope here) — but the gate staying silent about
    un-muted EXPOSED findings it does not check is not: a CI log that says nothing implies
    there was nothing to say."""
    import agent.run as run_mod
    monkeypatch.setattr(run_mod, "run_pipeline", lambda *a, **k: {
        "scope": {"reposScanned": 1},
        "auditCounts": {"DEPRECATED": 0, "REVIEW": 0, "EXPOSED": 2}, "delivered": []})
    rc = cli.main(_run_args(tmp_path, "--fail-on-deprecated"))
    err = capsys.readouterr().err
    assert rc == 0, "EXPOSED alone must not trip the gate — that is a separate policy decision"
    assert "2 EXPOSED" in err
    assert "not gated by --fail-on-deprecated" in err


def test_gate_fails_distinctly_when_sources_unreachable(monkeypatch, tmp_path):
    import agent.run as run_mod
    monkeypatch.setattr(run_mod, "run_pipeline", lambda *a, **k: {
        "scope": {"reposScanned": 1}, "auditCounts": {"DEPRECATED": 0, "REVIEW": 0},
        "coverage": {"osvErrors": 1, "eolErrors": 0}, "delivered": []})
    # 0 findings but a source was down -> exit 4 (couldn't check), NOT 0 (clean)
    assert cli.main(_run_args(tmp_path, "--fail-on-deprecated")) == 4

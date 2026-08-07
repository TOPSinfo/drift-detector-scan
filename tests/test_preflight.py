"""Pre-scan preflight — fail in 5 seconds on a misconfigured deployment, not after a
10-minute scan. The decision logic is a pure function over (config, environment) with the
GitLab probe injected, so every branch is testable without network."""
from agent.lib import preflight

_CFG = {
    "host": "git.x",
    "delivery": {"mode": "live", "dev_as_issues": True, "devops_project": "g/ops"},
    "auth": {"clone": "GITLAB_TOKEN", "persist": "GITLAB_TOKEN", "deliver": "GITLAB_TOKEN"},
    "notify": {"gchat": None},
}
_OK = lambda host, token: (True, "ok")


def test_ready_when_token_set_and_gitlab_reachable():
    problems, advisories = preflight.check(_CFG, {"GITLAB_TOKEN": "t"}, probe=_OK)
    assert problems == []


def test_missing_token_blocks_and_names_every_role_it_serves():
    problems, _ = preflight.check(_CFG, {}, probe=_OK)
    assert len(problems) == 1
    assert "GITLAB_TOKEN" in problems[0]
    for role in ("clone", "persist", "deliver"):
        assert role in problems[0]


def test_split_tokens_only_flag_the_unset_one():
    cfg = {**_CFG, "auth": {"clone": "GITLAB_TOKEN", "persist": "GITLAB_TOKEN",
                            "deliver": "DELIVER_PAT"}}
    problems, _ = preflight.check(cfg, {"GITLAB_TOKEN": "t"}, probe=_OK)
    assert len(problems) == 1 and "DELIVER_PAT" in problems[0] and "deliver" in problems[0]


def test_configured_but_unset_webhook_is_a_blocking_problem():
    cfg = {**_CFG, "notify": {"gchat": "GCHAT_WEBHOOK"}}
    problems, _ = preflight.check(cfg, {"GITLAB_TOKEN": "t"}, probe=_OK)
    assert any("GCHAT_WEBHOOK" in p for p in problems)


def test_mrs_target_in_live_mode_is_an_advisory_not_a_block():
    cfg = {**_CFG, "delivery": {"mode": "live", "dev_as_issues": False,
                                "devops_project": "g/ops"}}
    problems, advisories = preflight.check(cfg, {"GITLAB_TOKEN": "t"}, probe=_OK)
    assert problems == []
    assert any("Developer" in a for a in advisories)


def test_rejected_token_or_unreachable_host_blocks():
    problems, _ = preflight.check(_CFG, {"GITLAB_TOKEN": "t"},
                                  probe=lambda h, t: (False, "401 token rejected"))
    assert any("git.x" in p and "401" in p for p in problems)


def test_no_probe_skips_the_network_check():
    problems, _ = preflight.check(_CFG, {"GITLAB_TOKEN": "t"}, probe=None)
    assert problems == []


# --- the CLI wrapper's exit-code contract (this is what the workflow gates on) ---

def _cfg_file(tmp_path):
    p = tmp_path / "drift.yml"
    p.write_text("fleet: [https://git.x/g/a]\n")
    return str(p)


def test_cli_config_preflight_blocks_on_missing_token(tmp_path, monkeypatch):
    from agent import cli
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("DRIFT_GIT_TOKEN", raising=False)
    rc = cli.main(["config-preflight", "--config", _cfg_file(tmp_path), "--no-network"])
    assert rc == 2                                   # the workflow must stop before the scan


def test_cli_config_preflight_passes_when_token_present(tmp_path, monkeypatch):
    from agent import cli
    monkeypatch.setenv("GITLAB_TOKEN", "dummy")
    rc = cli.main(["config-preflight", "--config", _cfg_file(tmp_path), "--no-network"])
    assert rc == 0

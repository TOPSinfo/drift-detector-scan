import json
from agent.lib.secrets_scan import run_secrets_scan
from tests import gitleaks_fake


def test_run_secrets_scan_invokes_gitleaks_and_normalizes_matches():
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return gitleaks_fake.canned(
            gitleaks_fake.hit("generic-api-key", "config/feedvisor.php", 5,
                              commit="a1b2c3d", fingerprint="a1b2c3d:config/feedvisor.php:generic-api-key:5"))

    res = run_secrets_scan("/repo", run=fake_run)
    assert seen["args"][0] == "gitleaks"
    assert "detect" in seen["args"]
    assert "/repo" in seen["args"]
    assert res["matches"] == [{
        "ruleId": "generic-api-key", "path": "config/feedvisor.php", "line": 5,
        "commit": "a1b2c3d", "fingerprint": "a1b2c3d:config/feedvisor.php:generic-api-key:5",
    }]
    assert res["errors"] == []


def test_run_secrets_scan_never_carries_the_matched_secret_text():
    """gitleaks' own JSON report includes `Secret`/`Match` fields with the live credential
    text. run_secrets_scan must drop them — the whole point of a finding is to say WHERE a
    secret is, never to make a second copy of it inside our own report."""
    def fake_run(args):
        return gitleaks_fake.canned(
            gitleaks_fake.hit("generic-api-key", "x.php", 1, secret="sk_live_abc123REDACTME"))

    res = run_secrets_scan("/repo", run=fake_run)
    dumped = json.dumps(res)
    assert "sk_live_abc123REDACTME" not in dumped


def test_run_secrets_scan_on_a_clean_repo_returns_no_matches():
    res = run_secrets_scan("/repo", run=lambda args: gitleaks_fake.EMPTY)
    assert res == {"matches": [], "errors": []}

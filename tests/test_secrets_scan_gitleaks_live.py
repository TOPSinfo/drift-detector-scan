"""Live-binary regression tests for agent/gitleaks.toml's allowlist scoping.

Skipped when no gitleaks binary is installed (mirrors tests/test_engine_live.py's
pattern for ast-grep) — these are the guards this repo's own static TOML-structure
tests (in tests/test_secrets_scan.py) CANNOT provide, because gitleaks' allowlist
condition-combination behavior (whether `paths`/`regexes`/`targetRules` within one
[[allowlists]] entry AND or OR together) is a property of the running binary, not of
the file's structure. A 2026-09-07 review found exactly this gap the hard way: a
config that read correctly (line-scoped, per its own comment and a passing structural
test) actually suppressed an entire file, because gitleaks 8.30.1 ORs a `paths`
condition against a `regexes` condition in the same entry rather than ANDing them.
"""
import shutil
import subprocess

import pytest

from agent.lib.secrets_scan import _resolve_gitleaks, run_secrets_scan


def _find_gitleaks():
    p = _resolve_gitleaks()
    return p if shutil.which(p) or __import__("os").path.exists(p) else None


_GITLEAKS = _find_gitleaks()


def _git_repo(tmp_path, files: dict):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
                   cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "-q", "-m", "x"], cwd=repo, check=True)
    return repo


@pytest.mark.skipif(_GITLEAKS is None, reason="no gitleaks binary installed")
def test_sonar_project_key_allowlist_does_not_swallow_the_whole_file(tmp_path):
    """VERIFIED AGAINST A REAL BINARY (2026-09-07): the sonar.projectKey allowlist
    entry must suppress ONLY that specific line, not every line of whatever file it
    appears in. A prior draft of agent/gitleaks.toml combined this entry's line-content
    regex with a `paths` restriction on the same entry — gitleaks 8.30.1 ORs those two
    conditions rather than ANDing them, so the path match alone was enough to suppress
    the WHOLE file, hiding a real hardcoded token on a different line. Line 2 here is
    deliberately shaped to match `generic-api-key` — the SAME rule this entry's
    `targetRules` names — not a different rule (an earlier version of this exact test
    used an aws-access-token-shaped value on line 2, which passed for the wrong reason:
    that rule was never suppressed by this entry regardless of whether line-scoping
    worked, so the test caught nothing). This test fails if the OR-widening regression
    is reintroduced."""
    repo = _git_repo(tmp_path, {
        "sonar-project.properties":
            "sonar.projectKey=my_project_SyntheticTestSuffix1\n"
            "api_key=zK9pLmN3vQsRtUwXyZ1aB2cD4eF6gH8iJkLmNoPq\n",
    })
    res = run_secrets_scan(str(repo))
    assert res["errors"] == []
    lines = {m["line"] for m in res["matches"]}
    assert 1 not in lines, "sonar.projectKey (line 1) should be suppressed"
    assert 2 in lines, (
        "line 2 is a DIFFERENT generic-api-key match than the allowlisted line — "
        "if this is missing, the entry is suppressing the whole file again, not just "
        "the one line it names")


@pytest.mark.skipif(_GITLEAKS is None, reason="no gitleaks binary installed")
def test_sales_force_lead_csv_allowlist_does_not_swallow_unrelated_rules(tmp_path):
    """VERIFIED AGAINST A REAL BINARY (2026-09-07): the Salesforce Lead-export
    allowlist entry is scoped to aws-access-token/generic-api-key specifically (the
    two rules the real false positive matched) — an unrelated rule (private-key, a
    structural PEM-header match rather than a vendor-checksummed token, deliberately
    chosen so this fixture can't be mistaken for a real credential by an automated
    secret scanner) on the SAME allowlisted path must still fire. An entry with `paths`
    but no `targetRules` would suppress every rule on that path; this test fails if
    that regression is reintroduced."""
    repo = _git_repo(tmp_path, {
        "sales_force/Lead.csv":
            "id,name,note\n"
            "00XSyntheticRecordID,x,plain\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEAxSyntheticNotARealKeyBody0000000000000000000000\n"
            "-----END RSA PRIVATE KEY-----\n",
    })
    res = run_secrets_scan(str(repo))
    assert res["errors"] == []
    rule_ids = {m["ruleId"] for m in res["matches"]}
    assert "aws-access-token" not in rule_ids and "generic-api-key" not in rule_ids
    assert "private-key" in rule_ids, (
        "a rule NOT named in this entry's targetRules must still fire on the same path")


@pytest.mark.skipif(_GITLEAKS is None, reason="no gitleaks binary installed")
def test_sales_force_lead_csv_allowlist_does_not_apply_to_other_paths(tmp_path):
    """VERIFIED AGAINST A REAL BINARY (2026-09-07): the allowlist is scoped to the
    EXACT verified path (sales_force/Lead.csv), not any .csv file — a genuine
    AWS-console-exported accessKeys.csv anywhere else in a repo must still be caught."""
    repo = _git_repo(tmp_path, {
        "other_exports/accessKeys.csv": "Access key ID,Secret access key\n"
                                        "AKIAQZXNRT2FAKE7WXYZ,notarealsecretvalue\n",
    })
    res = run_secrets_scan(str(repo))
    assert res["errors"] == []
    assert any(m["ruleId"] == "aws-access-token" for m in res["matches"]), (
        "a .csv at a DIFFERENT path than the one verified must not be suppressed")

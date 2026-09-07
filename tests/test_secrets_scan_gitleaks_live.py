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
    export at some OTHER .csv path must still be caught. A structural PEM-header match
    (not a vendor-checksummed key shape) so this fixture can't be mistaken for a real
    credential by an automated secret scanner — GitHub's push protection blocked an
    earlier version of this fixture that used an AKIA-shaped value, since that shape
    alone (no checksum) is indistinguishable from a real AWS access key ID."""
    repo = _git_repo(tmp_path, {
        "other_exports/accessKeys.csv":
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEAxSyntheticNotARealKeyBody0000000000000000000000\n"
            "-----END RSA PRIVATE KEY-----\n",
    })
    res = run_secrets_scan(str(repo))
    assert res["errors"] == []
    assert any(m["ruleId"] == "private-key" for m in res["matches"]), (
        "a .csv at a DIFFERENT path than the one verified must not be suppressed")


@pytest.mark.skipif(_GITLEAKS is None, reason="no gitleaks binary installed")
def test_bmad_manifest_allowlist_does_not_swallow_unrelated_rules(tmp_path):
    """VERIFIED AGAINST A REAL BINARY (2026-09-07, root/vp-desktop-application and
    root/vp-panel-backend): the BMAD framework's own generated `.bmad/_cfg/files-
    manifest.csv` lists every installed file with its SHA256 CONTENT HASH — a fixed
    64-hex-char column that satisfies generic-api-key's entropy check on every single
    row. Reproduced directly: `gitleaks detect` on this exact file shape flagged the
    hash column, not any credential. Scoped to the exact tool-generated path (not any
    .csv) and to the one rule that fires, so a real secret elsewhere in the same repo —
    or a genuinely different CSV — must still be caught."""
    repo = _git_repo(tmp_path, {
        ".bmad/_cfg/files-manifest.csv":
            "type,name,module,path,hash\n"
            '"md","email-auth","bmm","bmad/bmm/testarch/knowledge/email-auth.md",'
            '"43f4cc3138a905a91f4a69f358be6664a790b192811b4dfc238188e826f6b41b"\n',
        "config/real.php": "$api_key = 'zK9pLmN3vQsRtUwXyZ1aB2cD4eF6gH8iJkLmNoPq';\n",
    })
    res = run_secrets_scan(str(repo))
    assert res["errors"] == []
    hits = {(m["path"], m["ruleId"]) for m in res["matches"]}
    assert (".bmad/_cfg/files-manifest.csv", "generic-api-key") not in hits, (
        "the manifest's own content-hash column must be suppressed")
    assert ("config/real.php", "generic-api-key") in hits, (
        "a real secret elsewhere in the SAME repo must still fire — the entry must not "
        "widen into a repo-wide suppression")


@pytest.mark.skipif(_GITLEAKS is None, reason="no gitleaks binary installed")
def test_bmad_manifest_allowlist_does_not_apply_to_other_paths(tmp_path):
    """VERIFIED AGAINST A REAL BINARY: scoped to the exact tool-generated filename, not
    any CSV with a `hash` column — a genuinely different CSV must still be scanned
    normally. A structural PEM-header match (not a vendor-checksummed key shape), same
    reasoning as the Salesforce path test above."""
    repo = _git_repo(tmp_path, {
        "other/export.csv":
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEAxSyntheticNotARealKeyBody0000000000000000000001\n"
            "-----END RSA PRIVATE KEY-----\n",
    })
    res = run_secrets_scan(str(repo))
    assert res["errors"] == []
    assert any(m["ruleId"] == "private-key" for m in res["matches"]), (
        "a CSV at a DIFFERENT path than the verified BMAD manifest must not be suppressed")


@pytest.mark.skipif(_GITLEAKS is None, reason="no gitleaks binary installed")
def test_truncated_example_jwt_header_placeholder_is_suppressed(tmp_path):
    """VERIFIED AGAINST A REAL BINARY (2026-09-07, root/vp-panel-backend's Swagger/
    OpenAPI doc comments): `token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."` — the
    UNIVERSAL, fixed HS256 JWT header (decodes to `{"alg":"HS256","typ":"JWT"}`, present
    in literally every HS256 JWT ever issued) glued to a literal, un-decodable "..."
    ellipsis — matched generic-api-key. The trailing "..." is what makes this
    unambiguously a documentation placeholder rather than a real, functional token (a
    real JWT has two more base64 segments after the header, never three literal dots).
    Anchored to the exact literal value, matched by VALUE not path, so a real leaked
    secret anywhere else is untouched."""
    repo = _git_repo(tmp_path, {
        "docs/api.md": 'token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."\n',
        "config/real.php": "$api_key = 'zK9pLmN3vQsRtUwXyZ1aB2cD4eF6gH8iJkLmNoPq';\n",
    })
    res = run_secrets_scan(str(repo))
    assert res["errors"] == []
    hits = {(m["path"], m["ruleId"]) for m in res["matches"]}
    assert ("docs/api.md", "generic-api-key") not in hits, (
        "the truncated example JWT header must be suppressed")
    assert ("config/real.php", "generic-api-key") in hits, (
        "a real secret elsewhere must still fire — the entry must match only this exact "
        "placeholder value, never widen into a rule- or path-level suppression")

"""The one shared definition of 'worse' and 'newer'. Both the MCP facade and the report
renderer rank with these, so a fix here fixes every surface at once."""
from agent.lib.ranking import severity_rank, semver_key, is_version


def test_semver_key_orders_numerically_not_lexically():
    # the real bug this exists to prevent: string sort says "1.10.0" < "1.7.4",
    # which once recommended the LOWER, still-vulnerable version.
    assert semver_key("1.10.0") > semver_key("1.7.4")
    assert max(["1.7.4", "1.10.0", "1.9.2"], key=semver_key) == "1.10.0"


def test_semver_key_handles_junk():
    assert semver_key("") == [0]
    assert semver_key(None) == [0]
    assert semver_key("v2.8.0") == [2, 8, 0]


def test_is_version_accepts_real_versions_and_rejects_git_shas():
    from agent.lib.ranking import is_version
    assert is_version("2.10.0")
    assert is_version("8.5.8")
    assert is_version("2.7.1-rc1")          # a pre-release is still a version
    assert is_version("v3.4.0")
    assert not is_version("767f6aa49fe20a2766b9843d01e3b7f7793df6a3")   # git SHA
    assert not is_version("")
    assert not is_version(None)
    assert not is_version("main")


def test_cve_severity_order():
    ranks = [severity_rank(s) for s in ("CRITICAL", "HIGH", "MODERATE", "LOW", "UNKNOWN")]
    assert ranks == sorted(ranks, reverse=True)
    assert len(set(ranks)) == 5                      # all distinct, no accidental ties


def test_severity_is_case_insensitive_and_none_safe():
    assert severity_rank("critical") == severity_rank("CRITICAL")
    assert severity_rank(None) == 0
    assert severity_rank("") == 0
    assert severity_rank("NONSENSE") == 0


def test_eol_ranked_by_overdue_ness():
    # php 7.4 died in 2022 and has no CVSS score; it must not rank below a LOW CVE.
    assert severity_rank("EOL", "DEPRECATED") == severity_rank("HIGH")
    assert severity_rank("EOL", "REVIEW") == severity_rank("MODERATE")
    assert severity_rank("EOL", "DEPRECATED") > severity_rank("LOW")


def test_sunset_ranked_by_overdue_ness():
    # the moat layer: a retired vendor API in live code. No live fixture produces these
    # yet (the catalog has no matching eBay entry), so this test is the only guard.
    assert severity_rank("SUNSET", "DEPRECATED") == severity_rank("HIGH")
    assert severity_rank("SUNSET", "REVIEW") == severity_rank("MODERATE")
    assert severity_rank("SUNSET", "DEPRECATED") > severity_rank("LOW")


def test_dated_severities_default_to_review_rank_without_status():
    # a caller that forgets `status` gets the conservative rank, never 0
    assert severity_rank("EOL") == severity_rank("MODERATE")
    assert severity_rank("SUNSET") == severity_rank("MODERATE")

"""The rollup: findings are advisories, actions are jobs. 30 torch CVEs are one upgrade."""
from agent.lib.actions import build_actions


def _cve(repo="r", ref="npm/axios", version="0.21.1", fixed="1.16.0",
         severity="HIGH", status="DEPRECATED", first_seen="2026-07-15", **kw):
    return {"repo": repo, "ref": ref, "kind": "cve", "version": version, "fixed": fixed,
            "severity": severity, "status": status, "first_seen": first_seen,
            "detail": "d", "recommendation": f"upgrade to >= {fixed}",
            "source_url": f"https://osv.dev/{fixed}", "tier": 1, **kw}


def test_findings_collapse_to_one_action_per_repo_and_ref():
    actions = build_actions([_cve(fixed="1.1.0"), _cve(fixed="1.2.0"), _cve(fixed="1.3.0")])
    assert len(actions) == 1
    assert actions[0]["finding_count"] == 3


def test_fix_version_is_the_semver_max_not_the_string_max():
    # the real torch case: 16 distinct 'fixed' values; only the max satisfies all 30 advisories.
    fixes = ["1.5.0", "2.8.0", "1.10.0", "1.7.4", "2.0.1", "1.13.0", "2.4.1", "1.9.0",
             "2.2.0", "1.11.0", "2.6.0", "1.8.1", "2.1.0", "1.12.0", "2.7.0", "1.6.0"]
    actions = build_actions([_cve(ref="python/torch", version="1.1.0", fixed=f) for f in fixes])
    assert actions[0]["fix_version"] == "2.8.0"      # not "2.7.0" (last), not "1.9.0" (string max)


def test_git_sha_fixed_values_are_ignored_in_fix_version():
    # OSV returns commit hashes as `fixed` for some advisories; a 40-char hex must never
    # out-rank a real version and become the recommendation.
    sha = "767f6aa49fe20a2766b9843d01e3b7f7793df6a3"
    a = build_actions([_cve(ref="python/torch", fixed="2.10.0"),
                       _cve(ref="python/torch", fixed=sha),
                       _cve(ref="python/torch", fixed="2.8.0")])[0]
    assert a["fix_version"] == "2.10.0"
    assert a["command"] == "pip install 'torch>=2.10.0'"


def test_group_with_only_sha_fixes_has_no_fix_version():
    sha = "767f6aa49fe20a2766b9843d01e3b7f7793df6a3"
    a = build_actions([_cve(ref="python/torch", fixed=sha)])[0]
    assert a["fix_version"] is None
    assert a["command"] is None


def test_same_ref_in_two_repos_is_two_actions():
    actions = build_actions([_cve(repo="a"), _cve(repo="b")])
    assert len(actions) == 2
    assert {a["repo"] for a in actions} == {"a", "b"}


def test_action_with_no_fix_is_still_emitted():
    actions = build_actions([_cve(fixed=None, recommendation="review advisory")])
    assert len(actions) == 1
    assert actions[0]["fix_version"] is None
    assert actions[0]["command"] is None
    assert actions[0]["recommendation"] == "review advisory"


def test_worst_and_status_aggregate_across_the_group():
    actions = build_actions([_cve(severity="LOW", status="REVIEW"),
                             _cve(severity="CRITICAL", status="DEPRECATED"),
                             _cve(severity="MODERATE", status="REVIEW")])
    assert actions[0]["worst"] == "CRITICAL"
    assert actions[0]["status"] == "DEPRECATED"      # DEPRECATED if ANY finding is
    assert actions[0]["critical_count"] == 1
    assert actions[0]["first_seen"] == "2026-07-15"


def test_ranking_critical_first_then_finding_count():
    small_crit = _cve(repo="z", ref="npm/a", severity="CRITICAL")
    many_high = [_cve(repo="a", ref="npm/b", severity="HIGH") for _ in range(30)]
    one_high = _cve(repo="a", ref="npm/c", severity="HIGH")
    ranked = build_actions([one_high, *many_high, small_crit])
    assert ranked[0]["ref"] == "npm/a"               # CRITICAL wins despite 1 finding, repo "z"
    assert ranked[1]["ref"] == "npm/b"               # 30 findings beat 1 at equal severity
    assert ranked[2]["ref"] == "npm/c"


def test_deprecated_outranks_review_regardless_of_severity():
    ranked = build_actions([_cve(ref="npm/a", severity="MODERATE", status="REVIEW"),
                            _cve(ref="npm/b", severity="LOW", status="DEPRECATED")])
    assert ranked[0]["ref"] == "npm/b"


def test_ties_break_stably_by_repo_then_ref():
    ranked = build_actions([_cve(repo="b", ref="npm/z"), _cve(repo="a", ref="npm/y"),
                            _cve(repo="a", ref="npm/x")])
    assert [(a["repo"], a["ref"]) for a in ranked] == [("a", "npm/x"), ("a", "npm/y"), ("b", "npm/z")]


def test_command_per_ecosystem():
    npm = build_actions([_cve(ref="npm/axios", fixed="1.16.0")])[0]
    assert npm["command"] == "npm install axios@^1.16.0"
    py = build_actions([_cve(ref="python/torch", fixed="2.8.0")])[0]
    assert py["command"] == "pip install 'torch>=2.8.0'"


def test_composer_ref_splits_on_the_first_slash_only():
    a = build_actions([_cve(ref="composer/aws/aws-sdk-php", fixed="3.371.4")])[0]
    assert a["eco"] == "composer"
    assert a["pkg"] == "aws/aws-sdk-php"
    assert a["command"] == "composer require aws/aws-sdk-php:^3.371.4"


def test_unknown_ecosystem_gets_no_command():
    a = build_actions([_cve(ref="cargo/serde", fixed="1.0.0")])[0]
    assert a["command"] is None


def test_eol_action_has_target_but_no_command():
    a = build_actions([{"repo": "r", "ref": "php", "kind": "eol", "version": "^7.4",
                        "fixed": "8.5.8", "severity": "EOL", "status": "DEPRECATED",
                        "first_seen": "2026-07-15", "detail": "php 7.4 end-of-life 2022-11-28",
                        "recommendation": "upgrade to 8.5.8",
                        "source_url": "https://endoflife.date/php", "tier": 1}])[0]
    assert a["fix_version"] == "8.5.8"
    assert a["command"] is None            # upgrading a runtime major is not a one-liner
    assert a["eco"] is None                # "php" has no "/"
    assert a["pkg"] == "php"
    assert a["worst"] == "EOL"


def test_sunset_action_preserves_files_and_emits_no_command():
    # the moat layer: ref is a bare vendor name, there is no `fixed`, and `files` is the payload.
    a = build_actions([{"repo": "r", "ref": "eBay", "kind": "sunset", "version": "v1",
                        "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
                        "detail": "eBay v1 retires 2026-09-30 · used at src/Ebay/x.php:11",
                        "date": "2026-09-30", "source_url": "https://developer.ebay.com/x",
                        "tier": 1, "recommendation": "migrate to Sell API before 2026-09-30",
                        "files": ["src/Ebay/x.php:11", "src/Ebay/y.php:40"]}])[0]
    assert a["eco"] is None and a["pkg"] == "eBay"
    assert a["fix_version"] is None
    assert a["command"] is None
    assert a["recommendation"] == "migrate to Sell API before 2026-09-30"
    assert a["files"] == ["src/Ebay/x.php:11", "src/Ebay/y.php:40"]
    assert a["kind"] == "sunset"


def test_files_defaults_to_empty_for_cve_actions():
    # cve/eol findings have no `files` key at all -> must use .get, not []
    assert build_actions([_cve()])[0]["files"] == []


def test_files_union_is_order_stable_and_capped_at_six():
    def sun(files):
        return {"repo": "r", "ref": "eBay", "kind": "sunset", "version": "*",
                "severity": "SUNSET", "status": "REVIEW", "first_seen": "2026-07-15",
                "detail": "d", "recommendation": "migrate", "source_url": "u", "tier": 1,
                "files": files}
    a = build_actions([sun(["a:1", "b:2"]), sun(["b:2", "c:3", "d:4", "e:5", "f:6", "g:7", "h:8"])])[0]
    assert a["files"] == ["a:1", "b:2", "c:3", "d:4", "e:5", "f:6"]      # deduped, in order, capped


def test_sources_are_deduped_and_order_stable():
    a = build_actions([_cve(fixed="1.0.0"), _cve(fixed="1.0.0"), _cve(fixed="2.0.0")])[0]
    assert a["sources"] == ["https://osv.dev/1.0.0", "https://osv.dev/2.0.0"]


def test_empty_input_returns_empty_list():
    assert build_actions([]) == []


def test_output_is_deterministic():
    findings = [_cve(repo="b", ref="npm/z"), _cve(repo="a", ref="npm/y", severity="CRITICAL")]
    assert build_actions(findings) == build_actions(findings)


def test_recommendation_matches_the_fix_version_it_reports():
    # prose and command must never point at different versions: an action saying
    # "upgrade to >= 1.5.0" while installing 2.8.0 sends the reader to a vulnerable release.
    fixes = ["1.5.0", "2.8.0", "1.10.0", "1.7.4"]
    a = build_actions([_cve(ref="python/torch", version="1.1.0", fixed=f) for f in fixes])[0]
    assert a["fix_version"] == "2.8.0"
    assert a["recommendation"] == "upgrade to >= 2.8.0"
    assert a["command"] == "pip install 'torch>=2.8.0'"


def test_apply_lifecycle_attaches_ranked_actions(tmp_path):
    from agent.lib.findings_state import apply_lifecycle
    audit = {"generated": "2026-07-15", "coverage": {},
             "findings": [_cve(repo="a", ref="npm/x", severity="CRITICAL"),
                          _cve(repo="a", ref="npm/y", severity="LOW", status="REVIEW")]}
    apply_lifecycle(audit, str(tmp_path), "2026-07-15")
    assert [a["ref"] for a in audit["actions"]] == ["npm/x", "npm/y"]   # ranked
    assert len(audit["findings"]) == 2                                   # findings untouched


def test_apply_lifecycle_excludes_muted_findings_from_actions(tmp_path):
    # a finding baselined (accepted-risk) before this run must vanish from `actions` (what the
    # team acts on) while remaining in `findings` (the untouched record for SARIF/BOM/MCP).
    from agent.lib.findings_state import add_to_baseline, apply_lifecycle, fingerprint

    muted = _cve(repo="a", ref="npm/muted", severity="CRITICAL")
    kept = _cve(repo="a", ref="npm/kept", severity="LOW", status="REVIEW")
    add_to_baseline(str(tmp_path), fingerprint(muted))

    audit = {"generated": "2026-07-15", "coverage": {}, "findings": [muted, kept]}
    apply_lifecycle(audit, str(tmp_path), "2026-07-15")

    assert [a["ref"] for a in audit["actions"]] == ["npm/kept"]
    assert {f["ref"] for f in audit["findings"]} == {"npm/muted", "npm/kept"}

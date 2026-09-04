"""Every leaked credential is its own thing — identity and grouping must say so.

`kind: "secret"` was added without touching the two places that give a finding an identity:
`findings_state.fingerprint` (new/resolved tracking + baseline muting) and `actions._group_key`
(one action = one job). Both fell through to a bare `ref`, which for a secret is the gitleaks
RULE id — so every `generic-api-key` hit in a repo collapsed onto one identity:

  - fixing 4 of 5 leaked keys of the same rule showed nothing resolved;
  - accepting ONE as a false positive muted every current AND FUTURE leak of that rule
    in that repo, forever;
  - 20 leaks in 20 files became 1 action whose `files` sample is capped at 6, so 14
    call-sites were silently dropped from the report.

The identity signal is `files[0]` — "path:line", the location agent/audit.py::_secret_findings
already puts in the finding. No new key on the finding dict (Task 3's contract is that a secret
finding carries exactly the keys _sunset_findings produces), and it is the same string the
report renders as the call-site, so identity and display can never drift apart.
"""
from agent.lib import findings_state as fs
from agent.lib.actions import build_actions


def _secret(repo="r", rule="generic-api-key", path="config/keys.php", line=5,
            first_seen="2026-09-01"):
    loc = f"{path}:{line}"
    return {"repo": repo, "kind": "secret", "ref": rule, "version": None, "domain": None,
            "operation": None, "path": path, "status": "EXPOSED", "severity": "CRITICAL",
            "detail": f"Hardcoded credential ({rule}) at {loc}", "date": None,
            "source_url": None, "tier": 0, "first_seen": first_seen,
            "recommendation": "Rotate the credential with its vendor.", "files": [loc]}


# ── 4a: fingerprint ───────────────────────────────────────────────────────────────

def test_two_leaks_of_the_same_rule_at_different_sites_are_different_fingerprints():
    a = _secret(path="config/keys.php", line=5)
    b = _secret(path="app/Services/Feed.php", line=88)
    assert fs.fingerprint(a) != fs.fingerprint(b), (
        "both leaks share the gitleaks rule id, so a ref-only identity merges them: "
        "muting one would mute the other, and fixing one would resolve neither")


def test_two_leaks_of_the_same_rule_at_different_lines_of_one_file_differ():
    assert fs.fingerprint(_secret(line=5)) != fs.fingerprint(_secret(line=41))


def test_the_same_leak_keeps_a_stable_fingerprint_across_runs():
    assert fs.fingerprint(_secret()) == fs.fingerprint(_secret(first_seen="2026-01-01"))


def test_the_same_site_in_two_repos_is_two_fingerprints():
    assert fs.fingerprint(_secret(repo="web")) != fs.fingerprint(_secret(repo="api"))


def test_muting_one_leak_does_not_mute_the_next_one_of_the_same_rule(tmp_path):
    """The consequence, end to end: baselining an accepted false positive must not blind the
    scanner to every future leak of that rule in that repo."""
    state = str(tmp_path)
    accepted = _secret(path="tests/fixtures/fake.php", line=3)
    fs.add_to_baseline(state, fs.fingerprint(accepted))

    audit = {"findings": [accepted, _secret(path="config/live.php", line=12)]}
    fs.apply_lifecycle(audit, state, "2026-09-04")
    live = [f for f in audit["findings"] if not f.get("suppressed")]
    assert [f["files"][0] for f in live] == ["config/live.php:12"]
    assert audit["counts"]["muted"] == 1


# ── 4b: action grouping ───────────────────────────────────────────────────────────

def test_distinct_leaks_of_one_rule_are_distinct_actions():
    findings = [_secret(path=f"src/f{i}.php", line=i) for i in range(1, 21)]
    actions = build_actions(findings)
    assert len(actions) == 20, (
        "collapsed into one action, _group_files' _MAX_FILES cap silently drops 14 of the "
        "20 call-sites from every rendered surface")
    assert {a["files"][0] for a in actions} == {f"src/f{i}.php:{i}" for i in range(1, 21)}


def test_a_secret_action_carries_the_leak_site_as_its_unit():
    """`unit` is what the row label and the action fingerprint disambiguate on — a sunset uses
    the retiring operation, a secret uses the leak's location."""
    a = build_actions([_secret(path="config/keys.php", line=5)])[0]
    assert a["unit"] == "config/keys.php:5"


def test_a_leak_of_a_different_rule_at_the_same_site_is_its_own_action():
    actions = build_actions([_secret(rule="generic-api-key"),
                             _secret(rule="aws-access-token")])
    assert len(actions) == 2


def test_non_secret_grouping_is_untouched():
    cve = {"repo": "r", "ref": "npm/axios", "kind": "cve", "version": "0.21.1",
           "fixed": "1.16.0", "severity": "HIGH", "status": "DEPRECATED",
           "files": ["a.js:1"], "recommendation": "x"}
    other = {**cve, "files": ["b.js:2"], "fixed": "1.17.0"}
    assert len(build_actions([cve, other])) == 1     # still one `npm install`

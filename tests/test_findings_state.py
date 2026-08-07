from agent.lib import findings_state as fs


def _cve(repo, pkg, vid, status="DEPRECATED"):
    return {"repo": repo, "kind": "cve", "ref": f"npm/{pkg}", "id": vid, "cve": vid,
            "version": "1.0.0", "status": status, "severity": "HIGH", "detail": "x",
            "source_url": "u", "tier": 1, "recommendation": "upgrade"}


def test_fingerprint_is_version_independent():
    a = _cve("r", "axios", "GHSA-1"); a["version"] = "0.21.1"
    b = _cve("r", "axios", "GHSA-1"); b["version"] = "1.7.4"
    assert fs.fingerprint(a) == fs.fingerprint(b)                 # same vuln, different version
    assert fs.fingerprint(_cve("r", "axios", "GHSA-2")) != fs.fingerprint(a)


def test_lifecycle_new_then_persist_then_resolve(tmp_path):
    state = str(tmp_path)
    # run 1: two findings, both new
    a1 = {"findings": [_cve("r", "axios", "G1"), _cve("r", "lodash", "G2")]}
    fs.apply_lifecycle(a1, state, "2026-07-01")
    assert a1["counts"]["new"] == 2 and a1["counts"]["resolved"] == 0
    assert all(f["first_seen"] == "2026-07-01" for f in a1["findings"])

    # run 2: axios persists (older first_seen), lodash resolved, redis is new
    a2 = {"findings": [_cve("r", "axios", "G1"), _cve("r", "redis", "G3")]}
    fs.apply_lifecycle(a2, state, "2026-07-08")
    d = a2["delta"]
    assert [f["ref"] for f in d["new"]] == ["npm/redis"]
    assert [r["ref"] for r in d["resolved"]] == ["npm/lodash"]
    axios = next(f for f in a2["findings"] if f["ref"] == "npm/axios")
    assert axios["first_seen"] == "2026-07-01"                    # preserved across runs
    assert a2["counts"] == {**a2["counts"], "new": 1, "resolved": 1}


def test_muted_findings_excluded_from_counts(tmp_path):
    state = str(tmp_path)
    f = _cve("r", "axios", "G1")
    fs.add_to_baseline(state, fs.fingerprint(f))
    audit = {"findings": [f, _cve("r", "lodash", "G2")]}
    fs.apply_lifecycle(audit, state, "2026-07-01")
    assert audit["counts"]["muted"] == 1
    assert audit["counts"]["DEPRECATED"] == 1                     # only lodash counts
    assert any(x.get("suppressed") for x in audit["findings"])
    fs.remove_from_baseline(state, fs.fingerprint(f))
    assert fs.load_baseline(state) == set()

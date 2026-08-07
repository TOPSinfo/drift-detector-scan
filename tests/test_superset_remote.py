from agent.lib.superset import to_superset_repo


def test_repo_doc_carries_remote_url_credential_free():
    meta = {"id": 1, "path": "svc", "head_sha": "abc",
            "remote_url": "https://github.com/o/r"}      # already normalized by git_meta
    doc = to_superset_repo(meta, {"runtimes": [], "frameworks": [], "sdks": []}, [])
    assert doc["remote_url"] == "https://github.com/o/r"
    assert "@" not in (doc["remote_url"] or "")          # never a credential


def test_repo_doc_remote_url_none_when_absent():
    meta = {"id": 1, "path": "svc", "head_sha": "abc"}    # no remote_url (local/no-origin)
    doc = to_superset_repo(meta, {"runtimes": [], "frameworks": [], "sdks": []}, [])
    assert doc["remote_url"] is None

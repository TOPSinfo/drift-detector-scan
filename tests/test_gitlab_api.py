"""The GitLab API client — correct URLs/methods/bodies, with an injected fetch (no network)."""
from agent.lib.gitlab_api import GitLab


def _recorder(responses):
    calls = []

    def fetch(url, *, method="GET", token=None, body=None):
        calls.append((method, url, body))
        return responses.pop(0) if responses else (200, None, "")
    fetch.calls = calls
    return fetch


def test_project_url_encodes_the_path():
    f = _recorder([(200, {"id": 5, "default_branch": "main"}, "")])
    assert GitLab("git.x", "t", fetch=f).project("group/repo")["id"] == 5
    method, url, _ = f.calls[0]
    assert method == "GET" and "/projects/group%2Frepo" in url


def test_create_issue_posts_the_body():
    f = _recorder([(201, {"iid": 3}, "")])
    GitLab("git.x", "t", fetch=f).create_issue("g/r", title="ti", description="de", labels="l")
    method, url, body = f.calls[0]
    assert method == "POST" and url.endswith("/issues")
    assert body == {"title": "ti", "description": "de", "labels": "l"}


def test_list_issues_follows_pagination():
    f = _recorder([(200, [{"iid": 1}], "2"), (200, [{"iid": 2}], "")])
    out = GitLab("git.x", "t", fetch=f).list_issues("g/r", labels="drift-detector")
    assert [i["iid"] for i in out] == [1, 2] and len(f.calls) == 2


def test_absent_project_and_branch_return_none_not_raise():
    f = _recorder([(404, None, ""), (404, None, "")])
    gl = GitLab("git.x", "t", fetch=f)
    assert gl.project("nope") is None
    assert gl.branch("g/r", "x") is None


def test_set_file_put_when_it_exists_post_when_not():
    f = _recorder([(200, {}, ""), (201, {}, "")])
    gl = GitLab("git.x", "t", fetch=f)
    gl.set_file("g/r", ".drift/M.md", branch="b", content="c", message="m", exists=True)
    gl.set_file("g/r", ".drift/M.md", branch="b", content="c", message="m", exists=False)
    assert f.calls[0][0] == "PUT" and f.calls[1][0] == "POST"


def _fake(routes):
    calls = []
    def fetch(url, *, method="GET", token=None, body=None):
        calls.append((method, url, body))
        for frag, resp in routes.items():
            if frag in url:
                return resp
        return (200, [], "")
    fetch.calls = calls
    return fetch, calls


def test_members_lists_inherited_members():
    fetch, _ = _fake({"/members/all": (200, [{"id": 5, "username": "ann", "access_level": 50},
                                             {"id": 6, "username": "bo", "access_level": 40}], "")})
    gl = GitLab("git.x", "t", fetch=fetch)
    assert gl.members("g/r") == [{"id": 5, "username": "ann", "access_level": 50},
                                 {"id": 6, "username": "bo", "access_level": 40}]


def test_user_id_resolves_username():
    fetch, _ = _fake({"/users?username=ann": (200, [{"id": 5, "username": "ann"}], "")})
    assert GitLab("git.x", "t", fetch=fetch).user_id("ann") == 5
    fetch2, _ = _fake({"/users?username=ghost": (200, [], "")})
    assert GitLab("git.x", "t", fetch=fetch2).user_id("ghost") is None


def test_create_issue_sends_assignee_ids():
    fetch, calls = _fake({"/issues": (201, {"iid": 1}, "")})
    GitLab("git.x", "t", fetch=fetch).create_issue("g/r", title="T", description="B",
                                                    labels="drift-detector", assignee_ids=[5])
    method, url, body = calls[-1]
    assert method == "POST" and body.get("assignee_ids") == [5]

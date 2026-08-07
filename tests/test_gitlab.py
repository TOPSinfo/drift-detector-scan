"""GitLab namespace expansion: a group OR user url -> all its accessible repos, else None."""
from agent.lib import gitlab


def _api(project_check, membership_pages, group_check=404):
    """Fake GitLab API. `project_check` = status for the `/projects/<path>` probe;
    `membership_pages` = page-number -> (status, data, next_page) for the membership list;
    `group_check` = status for the `/groups/<path>` probe (the tiebreaker when membership is
    empty: 200 = a real, empty group; else not a group -> expand returns None)."""
    def fetch(api_url, token):
        import re
        if "/groups/" in api_url:
            return (group_check, None, "")
        if "/projects/" in api_url and "membership" not in api_url:
            return (project_check, None, "")
        page = int(re.search(r"[?&]page=(\d+)", api_url).group(1))
        return membership_pages.get(page, (200, [], ""))
    return fetch


def _proj(ns_path, archived=False):
    return {"http_url_to_repo": f"https://git.x/{ns_path}.git",
            "path_with_namespace": ns_path, "archived": archived}


def test_expands_a_namespace_into_its_accessible_projects():
    # membership returns projects across namespaces; only those under acme/ are kept
    pages = {1: (200, [_proj("acme/web"), _proj("acme/api"), _proj("acme/old", archived=True),
                       _proj("other/thing")], "")}
    out = gitlab.expand_group("https://git.x/acme", token="t",
                              fetch=_api(project_check=404, membership_pages=pages))
    assert [p["path"] for p in out] == ["acme/web", "acme/api", "acme/old"]
    assert out[2]["archived"] is True
    assert "other/thing" not in [p["path"] for p in out]      # scoped to the namespace


def test_works_for_a_user_namespace_not_only_a_group():
    """The real case: git.x/example-org is a USER namespace (group endpoint would 404). The
    membership list still finds its projects."""
    pages = {1: (200, [_proj("example-org/amazonspapi")], "")}
    out = gitlab.expand_group("https://git.x/example-org", token="t",
                              fetch=_api(project_check=404, membership_pages=pages))
    assert [p["path"] for p in out] == ["example-org/amazonspapi"]


def test_paginates_fully():
    pages = {1: (200, [_proj("acme/a"), _proj("acme/b")], "2"),
             2: (200, [_proj("acme/c")], "")}
    out = gitlab.expand_group("https://git.x/acme", token="t",
                              fetch=_api(project_check=404, membership_pages=pages))
    assert [p["path"] for p in out] == ["acme/a", "acme/b", "acme/c"]


def test_a_project_path_is_not_a_namespace_returns_none():
    """host/acme/web IS a project — the project probe 200s, so expand returns None and the
    caller clones it directly instead of enumerating."""
    out = gitlab.expand_group("https://git.x/acme/web",
                              fetch=_api(project_check=200, membership_pages={}))
    assert out is None


def test_a_mid_enumeration_failure_returns_none_not_a_subset():
    """Silently scanning PART of a fleet is the miss this feature exists to prevent — a
    page failure aborts to None (fall back), never a partial list."""
    pages = {1: (200, [_proj("acme/a")], "2"), 2: (500, None, "")}
    out = gitlab.expand_group("https://git.x/acme",
                              fetch=_api(project_check=404, membership_pages=pages))
    assert out is None


def test_unreachable_api_returns_none():
    def boom(api, tok):
        raise ConnectionError("host down")
    assert gitlab.expand_group("https://git.x/acme", fetch=boom) is None


def test_a_real_namespace_the_token_sees_no_projects_in_is_empty_not_none():
    # a POSITIVE group confirmation (groups/<path> -> 200) is what justifies "empty group"
    out = gitlab.expand_group("https://git.x/empty",
                              fetch=_api(project_check=404, membership_pages={1: (200, [], "")},
                                         group_check=200))
    assert out == []


def test_a_404_project_with_no_children_returns_none_not_empty_group():
    """The demo bug: example-org/ebayapinew 404s as a project and is NOT a group, but empty
    membership made expand_group return [] — so the resolver reported 'group has no active
    projects' instead of the honest 'could not access this repo'. It must return None so the
    caller clones the URL directly and surfaces git's real not-found/no-access error."""
    out = gitlab.expand_group("https://git.x/example-org/ebayapinew",
                              fetch=_api(project_check=404, membership_pages={1: (200, [], "")},
                                         group_check=404))
    assert out is None


def test_bare_host_and_dot_git_handling():
    assert gitlab.expand_group("https://git.x",
                               fetch=_api(404, {1: (200, [], "")})) is None   # no path
    seen = {}
    def fetch(api, tok):
        seen.setdefault("first", api)
        return (404, None, "") if "/projects/" in api and "membership" not in api else (200, [], "")
    gitlab.expand_group("https://git.x/acme.git", fetch=fetch)
    assert "acme.git" not in seen["first"] and "projects/acme" in seen["first"]

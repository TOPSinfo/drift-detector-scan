"""The cross-fleet dependency edge — pure, deterministic, no I/O."""
from agent.lib import scope_edges as se


def test_identity_normalizes_scheme_scp_and_dotgit():
    canon = "git.example.com/grp/repo"
    assert se.identity("https://git.example.com/grp/repo.git") == canon
    assert se.identity("https://git.example.com/grp/repo/") == canon
    assert se.identity("git@git.example.com:grp/repo.git") == canon
    assert se.identity("https://GIT.example.com/GRP/Repo") == canon   # case-folded


def test_identity_empty_for_non_urls():
    assert se.identity("") == ""
    assert se.identity("just-a-slug") == ""
    assert se.identity("/local/path/repo") == ""


def test_missing_splits_present_from_referenced_but_absent():
    # marketplacehub declares two private deps; only amazonspapi is a fleet member.
    consumers = [{"repo": "marketplacehub", "deps": [
        "https://git.x/example-org/amazonspapi.git",
        "https://git.x/akshit/catchapi.git",
    ]}]
    fleet = {"git.x/example-org/amazonspapi"}          # catchapi is NOT in the fleet
    rows = se.find_missing(consumers, fleet)
    assert len(rows) == 1
    r = rows[0]
    assert [e["id"] for e in r["present"]] == ["git.x/example-org/amazonspapi"]
    assert [e["id"] for e in r["missing"]] == ["git.x/akshit/catchapi"]


def test_dep_with_no_identity_counts_as_missing():
    # an unparseable dep can't be proven in-fleet → treated as a blind spot, not silently kept
    rows = se.find_missing([{"repo": "x", "deps": ["not-a-url"]}], {"git.x/a/b"})
    assert rows[0]["missing"] == [{"url": "not-a-url", "id": ""}]
    assert rows[0]["present"] == []


def test_repo_with_no_private_deps_is_omitted():
    assert se.find_missing([{"repo": "clean", "deps": []}], set()) == []


def test_output_is_deterministic():
    consumers = [{"repo": "x", "deps": ["https://git.x/z/last.git", "https://git.x/a/first.git"]}]
    a = se.find_missing(consumers, set())
    b = se.find_missing(consumers, set())
    assert a == b
    assert [e["id"] for e in a[0]["missing"]] == ["git.x/a/first", "git.x/z/last"]   # sorted

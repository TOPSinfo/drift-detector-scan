import pytest
from agent.eval import clone


def _entry(repo="o/ebay-sdk-php", sha="a" * 40):
    return {"repo": repo, "url": f"https://github.com/{repo}.git", "sha": sha, "category": "ebay"}


def test_clones_absent_repo_then_checks_out_and_verifies(tmp_path):
    calls = []

    def fake_git(args, cwd=None):
        calls.append((args, cwd))
        if args[-1] == "HEAD" and "rev-parse" in args:
            return "a" * 40                       # HEAD == sha -> verified
        if "status" in args:
            return ""                             # clean tree
        return ""

    paths = clone.sync_corpus([_entry()], str(tmp_path), git=fake_git)
    joined = " ".join(" ".join(a) for a, _ in calls)
    assert "clone --filter=blob:none" in joined
    assert "checkout " + "a" * 40 in joined
    assert "rev-parse HEAD" in joined
    # `o__ebay-sdk-php`, not `ebay-sdk-php`: the checkout directory carries the ORG too,
    # so two repos with the same name under different orgs cannot share one checkout.
    assert paths == [str(tmp_path / "ebay" / "o__ebay-sdk-php")]


def test_hard_fails_when_head_does_not_match_sha(tmp_path):
    def fake_git(args, cwd=None):
        if "rev-parse" in args:
            return "b" * 40                       # HEAD != declared sha "a"*40
        return ""
    with pytest.raises(RuntimeError, match="SHA mismatch|a{6}"):
        clone.sync_corpus([_entry()], str(tmp_path), git=fake_git)


def test_refuses_a_dirty_tree(tmp_path):
    # pre-create the dir so it's treated as existing (fetch path)
    (tmp_path / "ebay" / "o__ebay-sdk-php" / ".git").mkdir(parents=True)

    def fake_git(args, cwd=None):
        if "status" in args:
            return " M somefile.php"              # dirty
        if "rev-parse" in args:
            return "a" * 40
        return ""
    with pytest.raises(RuntimeError, match="dirty|uncommitted"):
        clone.sync_corpus([_entry()], str(tmp_path), git=fake_git)


def test_git_status_failure_aborts_not_treated_as_clean(tmp_path):
    # pre-create the dir so it's treated as existing (fetch path)
    (tmp_path / "ebay" / "o__ebay-sdk-php" / ".git").mkdir(parents=True)
    checked_out = []

    def failing_git(args, cwd=None):
        if "status" in args:
            raise RuntimeError("git status failed: permission denied")
        if "checkout" in args:
            checked_out.append(args)
        if "rev-parse" in args:
            return "a" * 40
        return ""

    with pytest.raises(RuntimeError, match="status|permission"):
        clone.sync_corpus([_entry()], str(tmp_path), git=failing_git)
    assert checked_out == []          # never reached checkout -> no silent discard


def test_same_repo_name_under_different_orgs_gets_separate_checkouts(tmp_path):
    """REGRESSION: the sandbox path was `basename(repo)`, so `amzn/selling-partner-api-sdk`
    and `amzapi/selling-partner-api-sdk` — both real, both in the `sp` category — collided on
    one directory. The first was cloned there; the second then ran `git fetch origin <its sha>`
    inside the FIRST one's checkout and died with `upload-pack: not our ref`, which broke
    `drift-eval run sp` outright. Two different repos must never share a checkout."""
    calls = []

    def fake_git(args, cwd=None):
        calls.append((args, cwd))
        if "rev-parse" in args:
            return "a" * 40
        if "status" in args:
            return ""
        return ""

    entries = [_entry(repo="amzn/selling-partner-api-sdk"),
               _entry(repo="amzapi/selling-partner-api-sdk")]
    paths = clone.sync_corpus(entries, str(tmp_path), git=fake_git)
    assert len(set(paths)) == 2, f"both orgs collapsed onto one checkout: {paths}"
    # and neither may be fetched into a directory cloned for the other
    assert not any("fetch" in a for a, _ in calls), \
        "a fresh sandbox should CLONE both, never fetch into an existing checkout"

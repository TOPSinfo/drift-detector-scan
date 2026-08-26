"""The configured branch has to reach the clone, and a branch on a group has to be refused.

A group URL expands to many repos. `develop` meaning the same thing in all of them is an
assumption nobody verified, and both forgiving alternatives are worse: failing every repo without
that branch turns one config line into twenty errors, and falling back per-repo produces a scan
where some repos were read on develop and others on main with nothing in the report saying which.
"""
from agent.lib import source_resolver


def _fake_clone(seen):
    def clone(url, dest, *, branch=None):
        seen.append((url, branch))
        return False, "not cloned (test)"      # errors out; we only assert the call
    return clone


def test_the_configured_branch_reaches_the_clone(tmp_path):
    seen = []
    source_resolver.resolve_sources(
        [("https://git.example.com/team/repo-a", "develop")], str(tmp_path),
        clone=_fake_clone(seen), expand_group=lambda u: None)
    assert seen == [("https://git.example.com/team/repo-a", "develop")]


def test_an_entry_with_no_branch_asks_for_none(tmp_path):
    seen = []
    source_resolver.resolve_sources(
        [("https://git.example.com/team/repo-a", None)], str(tmp_path),
        clone=_fake_clone(seen), expand_group=lambda u: None)
    assert seen == [("https://git.example.com/team/repo-a", None)]


def test_a_bare_string_root_still_resolves(tmp_path):
    """Callers that were never updated must not silently start scanning the literal text
    "('https://…', None)" as a filesystem path."""
    seen = []
    source_resolver.resolve_sources(
        ["https://git.example.com/team/repo-a"], str(tmp_path),
        clone=_fake_clone(seen), expand_group=lambda u: None)
    assert seen == [("https://git.example.com/team/repo-a", None)]


def test_a_branch_on_a_group_fails_that_root_and_clones_nothing(tmp_path):
    """Refused where the answer is actually known — expand_group returning a list IS the only way
    to learn a URL is a namespace, so this cannot be checked at config-load time."""
    seen = []
    out = source_resolver.resolve_sources(
        [("https://git.example.com/team-group", "develop")], str(tmp_path),
        clone=_fake_clone(seen),
        expand_group=lambda u: [{"url": "https://git.example.com/team-group/r1.git",
                                 "path": "r1", "archived": False}])
    assert seen == [], "a group entry with a branch must not clone anything"
    assert out["errors"], "the root must be reported, not silently skipped"
    reason = out["errors"][0]["reason"]
    assert "branch" in reason and "develop" in reason, (
        f"the error must name the branch that caused it, got {reason!r}")


def test_a_group_without_a_branch_still_expands(tmp_path):
    seen = []
    source_resolver.resolve_sources(
        [("https://git.example.com/team-group", None)], str(tmp_path),
        clone=_fake_clone(seen),
        expand_group=lambda u: [{"url": "https://git.example.com/team-group/r1.git",
                                 "path": "r1", "archived": False}])
    assert seen == [("https://git.example.com/team-group/r1.git", None)]


# --- the clone itself ------------------------------------------------------------------------
import subprocess


def _record_git(calls, rc=0, stderr=""):
    """Stand in for subprocess.run so the argv can be asserted without touching git."""
    class R:
        def __init__(self, code, err):
            self.returncode, self.stderr, self.stdout = code, err, ""

    def run(cmd, **kw):
        calls.append(cmd)
        return R(rc, stderr)
    return run


def test_a_fresh_clone_asks_git_for_the_branch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", _record_git(calls))
    ok, _ = source_resolver._default_clone("https://git.example.com/t/r",
                                           str(tmp_path / "dest"), branch="develop")
    assert ok
    argv = calls[-1]
    assert "clone" in argv
    assert "--branch" in argv and argv[argv.index("--branch") + 1] == "develop"
    assert "--single-branch" in argv


def test_an_existing_clone_refetches_the_branch_not_the_default(tmp_path, monkeypatch):
    """THE trap in this change. The old fetch has no refspec, so FETCH_HEAD resolves to the
    remote's DEFAULT branch — an already-cloned repo would silently drift back to main on every
    run after the first, with nothing in the artifacts to show it."""
    dest = tmp_path / "dest"
    (dest / ".git").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(subprocess, "run", _record_git(calls))
    source_resolver._default_clone("https://git.example.com/t/r", str(dest), branch="develop")
    fetch = [c for c in calls if "fetch" in c][0]
    assert fetch[-1] == "develop", (
        f"fetch must name the branch as its refspec, got {fetch!r} — without it FETCH_HEAD is "
        f"the default branch and the configured branch is ignored from the second run onward")


def test_a_missing_branch_is_an_error_not_a_fallback(tmp_path, monkeypatch):
    """Someone asked for a specific branch and did not get it. Scanning a different one and
    reporting findings against it would be the tool being more confident than its evidence."""
    calls = []
    monkeypatch.setattr(subprocess, "run", _record_git(
        calls, rc=128, stderr="fatal: Remote branch develop not found in upstream origin"))
    ok, msg = source_resolver._default_clone("https://git.example.com/t/r",
                                             str(tmp_path / "dest"), branch="develop")
    assert not ok, "a missing branch must fail the repo, never fall back to the default"
    assert "develop" in msg, f"the message must name the branch asked for, got {msg!r}"


def test_an_existing_clone_on_another_branch_is_not_kept_when_the_fetch_fails(tmp_path,
                                                                              monkeypatch):
    """The no-branch path keeps a stale clone and says so, which is reasonable. With a branch it
    must NOT: that checkout is on some other ref, and scanning it would report the wrong code
    under the right repo's name."""
    dest = tmp_path / "dest"
    (dest / ".git").mkdir(parents=True)
    monkeypatch.setattr(subprocess, "run", _record_git([], rc=1, stderr="couldn't find remote ref"))
    ok, msg = source_resolver._default_clone("https://git.example.com/t/r", str(dest),
                                             branch="develop")
    assert not ok, "kept a checkout on the wrong branch and called the scan successful"
    assert "develop" in msg


def test_no_branch_keeps_todays_argv_exactly(tmp_path, monkeypatch):
    """The default path must not change: every fleet entry that names no branch is every entry
    that exists today."""
    calls = []
    monkeypatch.setattr(subprocess, "run", _record_git(calls))
    source_resolver._default_clone("https://git.example.com/t/r", str(tmp_path / "dest"))
    argv = calls[-1]
    assert "--branch" not in argv and "--single-branch" not in argv

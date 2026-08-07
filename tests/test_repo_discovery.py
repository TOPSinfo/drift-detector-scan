import os

from pathlib import Path

from agent.lib.repo_discovery import discover_repos


def _mkrepo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def test_finds_immediate_and_nested_repos(tmp_path):
    root = tmp_path / "root"
    _mkrepo(root / "a")
    _mkrepo(root / "group" / "b")
    _mkrepo(root / "group" / "sub" / "c")

    found = discover_repos([str(root)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["a", "group/b", "group/sub/c"]


def test_does_not_descend_into_a_found_repo(tmp_path):
    root = tmp_path / "root"
    _mkrepo(root / "a")
    _mkrepo(root / "a" / "vendored")

    found = discover_repos([str(root)])
    assert len(found) == 1
    abs_path, identity = found[0]
    assert identity == "a"
    assert Path(abs_path) == (root / "a").resolve()


def test_skips_node_modules_and_vendor(tmp_path):
    root = tmp_path / "root"
    _mkrepo(root / "node_modules" / "pkg")
    _mkrepo(root / "vendor" / "lib")

    found = discover_repos([str(root)])
    assert found == []


def test_multiple_roots_combined(tmp_path):
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    _mkrepo(root1 / "a")
    _mkrepo(root1 / "group" / "b")
    _mkrepo(root2 / "x")
    _mkrepo(root2 / "group" / "y")

    found = discover_repos([str(root1), str(root2)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["a", "group/b", "group/y", "x"]


def test_dedup_same_repo_via_two_roots(tmp_path):
    root1 = tmp_path / "root1"
    _mkrepo(root1 / "sub" / "repo")
    root2 = root1 / "sub"  # root2 is a plain subdir of root1; same repo reachable via both roots

    found = discover_repos([str(root1), str(root2)])
    assert len(found) == 1
    abs_path, _identity = found[0]
    assert Path(abs_path) == (root1 / "sub" / "repo").resolve()


def test_identity_collision_disambiguated(tmp_path):
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    _mkrepo(root1 / "app")
    _mkrepo(root2 / "app")

    found = discover_repos([str(root1), str(root2)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["root1/app", "root2/app"]


def test_root_itself_is_a_repo(tmp_path):
    root = tmp_path / "myrepo"
    _mkrepo(root)

    found = discover_repos([str(root)])
    assert len(found) == 1
    abs_path, identity = found[0]
    assert identity == "myrepo"
    assert Path(abs_path) == root.resolve()


def test_same_basename_roots_disambiguated(tmp_path):
    # Two roots that share a basename ("project"); each has an "app" repo.
    # Basename-only disambiguation would collapse both to "project/app" —
    # the fix prefixes relative to the common ancestor, keeping them distinct.
    parent = tmp_path / "parent"
    root1 = parent / "g1" / "project"
    root2 = parent / "g2" / "project"
    _mkrepo(root1 / "app")
    _mkrepo(root2 / "app")

    found = discover_repos([str(root1), str(root2)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["g1/project/app", "g2/project/app"]


def test_identity_is_order_independent(tmp_path):
    # Overlapping roots (one is an ancestor of the other). The repo's identity
    # must not depend on which root appears first in the list.
    team = tmp_path / "team"
    _mkrepo(team / "legacy" / "api")
    _mkrepo(team / "svc")
    legacy = team / "legacy"

    found_ab = discover_repos([str(team), str(legacy)])
    found_ba = discover_repos([str(legacy), str(team)])
    assert found_ab == found_ba

    identities = sorted(identity for _, identity in found_ab)
    # nearest-ancestor root for the api repo is `legacy` -> identity "api"
    assert identities == ["api", "svc"]


def test_symlink_cycle_terminates(tmp_path):
    root = tmp_path / "root"
    _mkrepo(root / "real")
    os.symlink(root, root / "loop", target_is_directory=True)  # cycle back to root

    found = discover_repos([str(root)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["real"]


def test_symlink_escaping_root_does_not_crash(tmp_path):
    # A repo reached via an in-tree symlink whose target lives OUTSIDE every
    # root: its resolved path has no ancestor root. Must not crash; identity
    # falls back to the in-tree walk path (the symlink name).
    outside = tmp_path / "outside"
    _mkrepo(outside / "shared")
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside / "shared", root / "vendored", target_is_directory=True)

    found = discover_repos([str(root)])
    assert len(found) == 1
    abs_path, identity = found[0]
    assert identity == "vendored"
    assert Path(abs_path) == (outside / "shared").resolve()


def test_same_basename_root_repos_disambiguated(tmp_path):
    # Two roots that are THEMSELVES repos and share a basename ("project").
    # Identity must not double the trailing segment ("g1/project/project").
    parent = tmp_path / "parent"
    r1 = parent / "g1" / "project"
    r2 = parent / "g2" / "project"
    _mkrepo(r1)
    _mkrepo(r2)

    found = discover_repos([str(r1), str(r2)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["g1/project", "g2/project"]

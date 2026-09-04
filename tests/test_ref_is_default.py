"""A scan of `develop` must not read as a scan of `main`.

`ref_is_default` was hardcoded True with the comment "best-effort locally (v1 simplification)".
Once a branch can be configured, that constant becomes a false statement in a published artifact:
without it, an override is unfalsifiable from the report — you would have to read the config file
to learn which code was actually scanned.
"""
import subprocess

from agent.lib import scan_util, source_resolver


def _repo(tmp_path, branch, name="r"):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "composer.json").write_text('{"require": {"php": "^8.2"}}')
    ident = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", "-b", branch, str(d)], check=True)
    subprocess.run(["git", *ident, "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", *ident, "-C", str(d), "commit", "-q", "-m", "x"], check=True)
    return str(d)


def test_git_meta_reports_the_ref_it_actually_read(tmp_path):
    assert scan_util.git_meta(_repo(tmp_path, "develop"))["ref"] == "develop"


def test_ref_is_default_is_false_when_a_branch_was_configured(tmp_path):
    meta = scan_util.git_meta(_repo(tmp_path, "develop"), configured_branch="develop")
    assert meta["ref_is_default"] is False, (
        "a repo scanned on a configured branch still claimed to be on its default — the override "
        "is then invisible in every published surface")


def test_ref_is_default_stays_true_when_no_branch_was_configured(tmp_path):
    assert scan_util.git_meta(_repo(tmp_path, "main"))["ref_is_default"] is True


def test_resolve_sources_reports_which_branch_each_project_was_asked_for(tmp_path):
    """The map that carries the fact from config to report. Without it `git_meta` has no way to
    know a branch was configured — the checked-out ref alone cannot tell you whether someone
    ASKED for it or the remote merely defaulted to it."""
    local = _repo(tmp_path, "develop", name="proj")

    def clone(url, dest, *, branch=None):
        return False, "unused"

    out = source_resolver.resolve_sources([(local, "develop")], str(tmp_path / "state"),
                                          clone=clone, expand_group=lambda u: None)
    assert out["projects"], "the local root should have resolved"
    abs_dir = out["projects"][0][0]
    assert out["branches"].get(abs_dir) == "develop"


def test_a_root_with_no_branch_has_no_entry_in_the_map(tmp_path):
    local = _repo(tmp_path, "main", name="proj")

    def clone(url, dest, *, branch=None):
        return False, "unused"

    out = source_resolver.resolve_sources([(local, None)], str(tmp_path / "state"),
                                          clone=clone, expand_group=lambda u: None)
    abs_dir = out["projects"][0][0]
    assert out["branches"].get(abs_dir) is None


def test_the_projects_tuple_shape_is_unchanged(tmp_path):
    """The branch is carried in a SEPARATE map on purpose: `projects` is documented as
    (abs_dir, identity, kind) and unpacked positionally in inventory_scan and in existing tests.
    Widening it would have been a silent breaking change to every one of those sites."""
    local = _repo(tmp_path, "main", name="proj")

    def clone(url, dest, *, branch=None):
        return False, "unused"

    out = source_resolver.resolve_sources([(local, "main")], str(tmp_path / "state"),
                                          clone=clone, expand_group=lambda u: None)
    assert all(len(p) == 3 for p in out["projects"])


def test_a_real_scan_marks_the_repo_as_not_on_its_default(tmp_path):
    """END-TO-END. git_meta being correct is not enough: the fact has to survive
    resolve_sources -> inventory_scan -> scan_repo -> the repo record, or the report still
    claims every repo is on its default branch."""
    from agent import inventory_scan
    from tests import astgrep_fake, gitleaks_fake

    root = tmp_path / "root"
    _repo(root, "develop", name="proj")          # the ROOT holds the checkout, as callers pass it
    out = inventory_scan.scan_folder([(str(root), "develop")],
                                     str(tmp_path / "state"), "2026-08-26",
                                     engine="semgrep", run=lambda a: astgrep_fake.canned(),
                                     secrets_run=lambda a: gitleaks_fake.EMPTY)
    rec = out["doc"]["repos"][0]
    assert rec["ref"] == "develop"
    assert rec["ref_is_default"] is False, (
        "the configured branch was lost between resolve_sources and the repo record — the "
        "report would say this repo is on its default branch")

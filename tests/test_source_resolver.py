"""Ingestion: a checkout, a plain folder, or a URL all resolve to scannable projects."""
import os
import subprocess

import pytest

from agent.lib import source_resolver as sr


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _make_repo(path, filename="OrdersApi.php"):
    path.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text('<?php $u="https://sellingpartnerapi-na.amazon.com/orders/v0/o";')
    _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "x")


# --------------------------------------------------------------------- url classification
@pytest.mark.parametrize("u", ["https://git.example.com/example-org/amazonspapi",
                               "http://x/y", "git@github.com:o/r.git", "ssh://g/r",
                               "git://h/r"])
def test_urls_are_recognised(u):
    assert sr.is_url(u)


@pytest.mark.parametrize("p", ["/home/x/repo", "./rel", "../up", "C:/x", "repo"])
def test_local_paths_are_not_urls(p):
    assert not sr.is_url(p)


def test_slug_is_stable_and_disambiguates_shared_basenames():
    a = sr.slug("https://git.example.com/example-org/amazonspapi")
    b = sr.slug("https://github.com/other/amazonspapi")
    assert a == sr.slug("https://git.example.com/example-org/amazonspapi")   # stable
    assert a != b and "amazonspapi" in a                                # disambiguated
    assert "/" not in a and ":" not in a                                # fs-safe


# --------------------------------------------------------------------- the three shapes
def test_local_git_checkout(tmp_path):
    _make_repo(tmp_path / "repo")
    out = sr.resolve_sources([str(tmp_path / "repo")], str(tmp_path / "state"))
    assert not out["errors"]
    assert len(out["projects"]) == 1
    assert out["projects"][0][2] == "local-git"


def test_a_plain_folder_is_scanned_as_one_project(tmp_path):
    """The zip case: real code, no .git. Resolves to a project, kind local-plain."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "OrdersApi.php").write_text('<?php $u="https://x/orders/v0/o";')
    out = sr.resolve_sources([str(plain)], str(tmp_path / "state"))
    assert not out["errors"]
    assert len(out["projects"]) == 1
    assert out["projects"][0][2] == "local-plain"


def test_a_url_is_cloned_then_scanned(tmp_path):
    """Exercises the REAL clone path via a file:// URL — no network, same code."""
    _make_repo(tmp_path / "origin")
    url = f"file://{tmp_path / 'origin'}"
    state = tmp_path / "state"
    out = sr.resolve_sources([url], str(state))
    assert not out["errors"], out["errors"]
    assert len(out["projects"]) == 1
    abs_dir, ident, kind = out["projects"][0]
    assert kind == "remote"
    assert (state / "sources").as_posix() in abs_dir      # cloned under state/sources
    assert (state / "sources").exists()


def test_a_second_resolve_updates_the_existing_clone_not_re_clones(tmp_path):
    _make_repo(tmp_path / "origin")
    url = f"file://{tmp_path / 'origin'}"
    state = str(tmp_path / "state")
    first = sr.resolve_sources([url], state)["projects"][0][0]
    second = sr.resolve_sources([url], state)               # must not error on existing dir
    assert second["projects"][0][0] == first
    assert not second["errors"]


# --------------------------------------------------------------------- errors, never silent
def test_a_failing_clone_is_an_error_not_a_silent_drop(tmp_path):
    out = sr.resolve_sources(["https://no.such.host.invalid/x/y.git"], str(tmp_path / "s"),
                             clone=lambda url, dest: (False, "host not found"),
                             expand_group=lambda url: None)
    assert out["projects"] == []
    assert out["errors"] and "could not clone" in out["errors"][0]["reason"]


def test_a_nonexistent_local_path_is_an_error(tmp_path):
    out = sr.resolve_sources([str(tmp_path / "nope")], str(tmp_path / "s"))
    assert out["projects"] == []
    assert out["errors"]


def test_an_empty_folder_with_no_code_is_an_error_not_a_project(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = sr.resolve_sources([str(empty)], str(tmp_path / "s"))
    assert out["projects"] == []
    assert out["errors"]


def test_one_or_many_mixed(tmp_path):
    _make_repo(tmp_path / "gitrepo")
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("import requests; requests.get('https://x/v1/y')")
    out = sr.resolve_sources([str(tmp_path / "gitrepo"), str(plain)], str(tmp_path / "s"))
    assert not out["errors"]
    kinds = sorted(k for _, _, k in out["projects"])
    assert kinds == ["local-git", "local-plain"]


# ------------------------------------------------- the private-URL auth path (security)
def test_token_is_passed_to_git_but_never_written_to_argv_or_disk(tmp_path, monkeypatch):
    """The claim behind 'clone reuses machine auth, token never persisted': a GITLAB_TOKEN
    must reach git via a credential helper that READS the env var at run time, so the
    secret value never appears in the process argv (visible in `ps`) nor in .git/config.
    """
    import subprocess as _sp
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env_has_token"] = "DRIFT_CLONE_TOKEN" in (kw.get("env") or {})
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    monkeypatch.setattr(_sp, "run", fake_run)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-SECRETVALUE123")
    ok, _ = sr._default_clone("https://git.example.com/example-org/amazonspapi.git",
                              str(tmp_path / "dest"))
    assert ok
    argv = " ".join(captured["cmd"])
    # the credential helper is wired, referencing the ENV VAR, not the literal secret
    assert "credential.helper" in argv
    assert "DRIFT_CLONE_TOKEN" in argv          # the env var name is referenced
    assert "glpat-SECRETVALUE123" not in argv   # the SECRET itself is never in argv
    assert captured["env_has_token"]            # it travels in the environment instead


def test_no_token_means_plain_clone_reusing_machine_auth(tmp_path, monkeypatch):
    """With no token in the env, the tool adds no credential args at all — git uses the
    machine's own helper / SSH keys, exactly 'reuse machine auth'."""
    import subprocess as _sp
    captured = {}
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("DRIFT_GIT_TOKEN", raising=False)

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    monkeypatch.setattr(_sp, "run", fake_run)
    sr._default_clone("https://x/y.git", str(tmp_path / "d"))
    assert "credential.helper" not in " ".join(captured["cmd"])


def test_clone_via_https_does_not_persist_a_token_in_git_config(tmp_path):
    """End-to-end on a real (file://) clone with a token set: the stored remote URL must
    be tokenless. file:// ignores the token, but the non-persistence property is the same
    code path and is what a leaked-secret audit would check."""
    import os
    _make_repo(tmp_path / "origin")
    dest = tmp_path / "dest"
    os.environ["GITLAB_TOKEN"] = "glpat-SHOULDNOTPERSIST"
    try:
        ok, _ = sr._default_clone(f"file://{tmp_path/'origin'}", str(dest))
    finally:
        del os.environ["GITLAB_TOKEN"]
    assert ok
    cfg = (dest / ".git" / "config").read_text()
    assert "glpat-SHOULDNOTPERSIST" not in cfg, "a token must never be written to .git/config"


# ------------------------------------------------- the plan command (approval gate)
def test_plan_reports_projects_and_errors_without_scanning(tmp_path, capsys):
    from agent.cli import main
    _make_repo(tmp_path / "repo")
    plain = tmp_path / "plain"; plain.mkdir()
    (plain / "a.php").write_text('<?php $u="https://x/orders/v0/o";')
    rc = main(["plan", "--root", str(tmp_path / "repo"), "--root", str(plain),
               "--root", str(tmp_path / "nope"), "--state", str(tmp_path / "s")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "git repo" in out and "plain folder" in out
    assert "2 project(s) will scan" in out
    # a scan would have written inventory.json; plan must NOT
    assert not (tmp_path / "s" / "inventory.json").exists()


def test_plan_exits_4_when_nothing_resolves(tmp_path):
    from agent.cli import main
    rc = main(["plan", "--root", str(tmp_path / "gone"), "--state", str(tmp_path / "s")])
    assert rc == 4


# ------------------------------------------------- GitLab group expansion (fleet scan)
def test_a_gitlab_group_url_expands_to_every_member_repo(tmp_path):
    """The consultancy case: point at a group, scan the whole fleet. Each member repo is
    cloned and scanned; you cannot miss one you didn't list."""
    _make_repo(tmp_path / "web")
    _make_repo(tmp_path / "api")
    group = [{"url": f"file://{tmp_path/'web'}", "path": "acme/web", "archived": False},
             {"url": f"file://{tmp_path/'api'}", "path": "acme/api", "archived": False},
             {"url": f"file://{tmp_path/'old'}", "path": "acme/old", "archived": True}]
    out = sr.resolve_sources(["https://git.x/acme"], str(tmp_path / "state"),
                             expand_group=lambda url: group)
    # both active repos cloned + scanned; the archived one skipped, no error for it
    assert len(out["projects"]) == 2
    assert all(k == "remote" for _, _, k in out["projects"])
    assert not out["errors"]


def test_an_empty_or_all_archived_group_is_an_error_not_a_silent_pass(tmp_path):
    out = sr.resolve_sources(["https://git.x/ghost"], str(tmp_path / "s"),
                             expand_group=lambda url: [{"url": "file:///x", "path": "g/z",
                                                        "archived": True}])
    assert out["projects"] == []
    assert out["errors"] and "no active projects" in out["errors"][0]["reason"]


def test_a_non_group_url_falls_back_to_single_repo_clone(tmp_path):
    """expand_group returns None (it's a project, not a group) -> the URL is cloned directly."""
    _make_repo(tmp_path / "solo")
    out = sr.resolve_sources([f"file://{tmp_path/'solo'}"], str(tmp_path / "s"),
                             expand_group=lambda url: None)
    assert len(out["projects"]) == 1 and out["projects"][0][2] == "remote"


def test_group_and_explicit_member_resolve_once_not_twice(tmp_path):
    """SHIPPED BUG (verify caught it): a fleet listing BOTH the `marketplacehub` group AND
    `marketplacehub/marketplacehub-api` (a member of it) resolved marketplacehub-api twice — the group
    yields `…/marketplacehub-api.git`, the explicit entry `…/marketplacehub-api`, which slug to
    different clone dirs, so the abs-dir dedupe missed them. Result: the repo scanned twice
    and drift.md rendered two identical findings rows. Dedupe by canonical git identity."""
    import pathlib

    def fake_clone(url, dest):
        _make_repo(pathlib.Path(dest))
        return (True, "")

    def fake_expand(url):
        if url.rstrip("/").endswith("/marketplacehub"):
            return [{"url": "https://git.x/marketplacehub/marketplacehub-api.git",
                     "archived": False, "path": "marketplacehub/marketplacehub-api"}]
        return None

    out = sr.resolve_sources(
        ["https://git.x/marketplacehub", "https://git.x/marketplacehub/marketplacehub-api"],
        str(tmp_path / "s"), clone=fake_clone, expand_group=fake_expand)
    assert not out["errors"], out["errors"]
    assert len(out["projects"]) == 1, out["projects"]     # one repo, not two

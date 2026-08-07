import pytest
from agent.lib import scan_util
from agent.lib.scan_util import git_meta, normalize_remote, resolve_engine


def test_repo_scope_id_uses_git_identity_not_local_path():
    # REGRESSION (absorb-gate bug): a repo-scoped idiom is matched on the git remote identity, so
    # the gate and the scan pipeline must derive repo_id the SAME way. The gate used to pass the
    # local checkout path — which _repo_in_scope can't key on — so an idiom scoped to `org/repo`
    # silently never applied for a clone dir named differently (double-break_spapi-php).
    ident = scan_util.repo_scope_id(
        "/home/ci/clones/double-break_spapi-php",
        {"remote_url": "github.com/double-break/spapi-php"})
    assert ident == "github.com/double-break/spapi-php"      # identity, NOT the local path


def test_repo_scope_id_falls_back_to_path_without_remote():
    # a local checkout with no remote: best-effort fall back to the path (unchanged behavior).
    assert scan_util.repo_scope_id("/tmp/x/foo", {"remote_url": None}) == "/tmp/x/foo"


def test_git_meta_from_injected_run():
    calls = []

    def fake(args):
        calls.append(args)
        return {"rev-parse HEAD": "abc123",
                "rev-parse --abbrev-ref HEAD": "main",
                "remote get-url origin": "git@github.com:o/r.git",
                "log -1 --format=%cI": "2026-07-10T00:00:00Z"}[" ".join(args[2:])]

    meta = git_meta("/repo", run=fake)
    assert meta == {"head_sha": "abc123", "ref": "main",
                    "remote_url": "https://github.com/o/r",
                    "last_activity_at": "2026-07-10T00:00:00Z", "ref_is_default": True}
    assert calls[0][:2] == ["-C", "/repo"]                      # git -C <repo> ...


def test_git_meta_empty_when_no_git():
    meta = git_meta("/repo", run=lambda args: "")
    assert meta["head_sha"] == "" and meta["ref"] == ""


def test_resolve_engine_raises_when_absent(monkeypatch):
    import agent.lib.scan_util as su
    monkeypatch.setattr(su.shutil, "which", lambda name: None)
    monkeypatch.setattr(su.os.path, "exists", lambda p: False)
    with pytest.raises(RuntimeError, match="ast-grep"):
        resolve_engine()


def test_resolve_engine_finds_on_path(monkeypatch):
    import agent.lib.scan_util as su
    monkeypatch.setattr(su.os.path, "exists", lambda p: False)      # ignore any locally-installed binary
    monkeypatch.setattr(su.shutil, "which", lambda name: "/usr/bin/ast-grep" if name == "ast-grep" else None)
    assert resolve_engine() == "/usr/bin/ast-grep"


# --- normalize_remote: safety-critical git-remote normalizer -------------------
# A token in the remote must NEVER survive — it would otherwise land in the shared dashboard.html.

def test_scp_ssh_remote():
    assert normalize_remote("git@github.com:owner/repo.git") == "https://github.com/owner/repo"


def test_ssh_scheme_remote():
    assert normalize_remote("ssh://git@github.com/owner/repo.git") == "https://github.com/owner/repo"


def test_plain_https_strips_dot_git():
    assert normalize_remote("https://github.com/owner/repo.git") == "https://github.com/owner/repo"


def test_https_with_embedded_token_is_stripped():
    # THE load-bearing case: a CI clone URL carrying a token must lose it.
    fake = "glpat-" + "SECRET"   # fake credential, assembled so no basic-auth literal ships
    out = normalize_remote(f"https://oauth2:{fake}@git.example.com/example-org/ebayapi.git")
    assert out == "https://git.example.com/example-org/ebayapi"
    assert fake not in out and "@" not in out


def test_self_hosted_gitlab_host_preserved():
    assert normalize_remote("git@git.example.com:example-org/ebayapi.git") == \
        "https://git.example.com/example-org/ebayapi"


def test_garbage_and_empty_return_none():
    assert normalize_remote("not-a-remote") is None
    assert normalize_remote("") is None
    assert normalize_remote(None) is None


def test_git_meta_captures_normalized_remote():
    def fake_git(args):
        if "get-url" in args:
            return "https://user:token@github.com/o/r.git"
        return "abc123" if "rev-parse" in args and "HEAD" == args[-1] else ""
    meta = git_meta("/repo", run=fake_git)
    assert meta["remote_url"] == "https://github.com/o/r"      # token stripped at capture

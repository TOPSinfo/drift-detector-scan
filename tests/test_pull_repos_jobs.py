import subprocess

from agent.run import _pull_repos


def _git_init(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / "composer.json").write_text('{"require": {}}')
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def test_pull_repos_pulls_every_repo_when_parallel(tmp_path):
    for name in ("a", "b", "c"):
        _git_init(tmp_path / name)
    pulled = []

    _pull_repos([tmp_path], pulled.append, jobs=3)

    assert sorted(p.rsplit("/", 1)[-1] for p in pulled) == ["a", "b", "c"]


def test_pull_repos_still_ignores_a_repo_that_will_not_pull(tmp_path):
    """Best-effort is load-bearing: a repo that won't fast-forward is scanned as-is,
    and must not take the whole pull phase down with it."""
    for name in ("a", "b"):
        _git_init(tmp_path / name)
    seen = []

    def runner(path):
        seen.append(path)
        raise RuntimeError("cannot fast-forward")

    _pull_repos([tmp_path], runner, jobs=2)          # must not raise

    assert len(seen) == 2

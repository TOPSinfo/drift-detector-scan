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


# ── the shape the CONFIG path actually passes ─────────────────────────────────────────────────

def test_pull_repos_accepts_the_fleet_pair_shape(tmp_path):
    """THE BUG. `_cmd_run` normalises roots to `[(url_or_path, branch|None)]` so the --root and
    --config forms cannot diverge downstream — but `_pull_repos` hands roots straight to
    `discover_repos`, which does `Path(r).resolve()`. A pair is not a PathLike, so every
    `run --config <yml> --pull` died with

        TypeError: argument should be a str or an os.PathLike object ... not 'tuple'

    before a single repo was scanned. That is the exact command the scheduled CI job runs
    (`.gitlab-ci.yml`: `run --config config/drift.yml --state state --now $(date +%F) --pull`),
    so the branch-override feature would have taken every weekly fleet scan down on first fire.

    Every existing test here passes bare paths, which is why it shipped green.
    """
    for name in ("a", "b"):
        _git_init(tmp_path / name)
    pulled = []

    _pull_repos([(tmp_path, None)], pulled.append, jobs=1)

    assert sorted(p.rsplit("/", 1)[-1] for p in pulled) == ["a", "b"]


def test_pull_repos_ignores_a_remote_url_rather_than_crashing(tmp_path):
    """A fleet is URLs, not paths. Cloning and fetching them is `resolve_sources`' job on the
    scan path; `--pull` only fast-forwards repos that are already local working trees. A URL
    resolves to no such tree, so it contributes nothing here — quietly, as it did before the
    pair shape existed."""
    _git_init(tmp_path / "a")
    pulled = []

    _pull_repos([("https://git.example.com/g/x", "dev"), (tmp_path, None)],
                pulled.append, jobs=1)

    assert [p.rsplit("/", 1)[-1] for p in pulled] == ["a"]

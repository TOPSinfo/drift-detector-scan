import json
import subprocess

from agent.inventory_scan import scan_folder


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _empty_engine(args):
    return json.dumps([])


def test_scan_folder_preserves_repo_order_when_parallel(tmp_path):
    """Repo records must come back in discovery order, so record['id'] and every
    downstream index mean the same thing at --jobs 4 as at --jobs 1."""
    root = tmp_path / "repos"
    for name in ("alpha", "bravo", "charlie", "delta"):
        _git_init(root / name, {"composer.json": '{"require": {"php": "^7.4"}}'})

    serial = scan_folder([root], tmp_path / "s1", "2026-08-25", run=_empty_engine, jobs=1)
    parallel = scan_folder([root], tmp_path / "s4", "2026-08-25", run=_empty_engine, jobs=4)

    names_serial = [r["path"] for r in serial["doc"]["repos"]]
    names_parallel = [r["path"] for r in parallel["doc"]["repos"]]
    assert names_parallel == names_serial
    assert [r["id"] for r in parallel["doc"]["repos"]] == [r["id"] for r in serial["doc"]["repos"]]


def test_scan_folder_records_an_erroring_repo_rather_than_dropping_it(tmp_path):
    """'Cannot see' is not 'clean' - a repo that blows up must land in reposErrored."""
    root = tmp_path / "repos"
    for name in ("ok1", "boom", "ok2"):
        _git_init(root / name, {"composer.json": '{"require": {}}'})

    def engine(args):
        if any("boom" in str(a) for a in args):
            raise RuntimeError("engine crashed")
        return json.dumps([])

    out = scan_folder([root], tmp_path / "state", "2026-08-25", run=engine, jobs=3)

    errored = [e["repo"] for e in out["doc"]["coverage"]["reposErrored"]]
    assert any("boom" in name for name in errored)
    assert out["doc"]["coverage"]["reposScanned"] == 3

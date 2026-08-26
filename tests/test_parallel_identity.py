"""The guarantee --jobs rests on: scheduling changes when work happens, never what is
concluded. If this test cannot be made to pass, the feature does not ship."""
import json
import subprocess

from agent.run import run_pipeline


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _empty_engine(args):
    return json.dumps([])


def _no_network(url, *, method="GET", body=None, timeout=20):
    return {}


def _fixture_fleet(root):
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^7.4"}}'})
    _git_init(root / "api", {"composer.json": '{"require": {"guzzlehttp/guzzle": "^6.0"}}'})
    _git_init(root / "ui", {"package.json": '{"dependencies": {"axios": "0.21.0"}}'})
    _git_init(root / "svc", {"composer.json": '{"require": {"php": "^8.1"}}'})
    _git_init(root / "job", {"package.json": '{"dependencies": {"moment": "2.20.0"}}'})


def test_serial_and_parallel_scans_produce_identical_artifacts(tmp_path, monkeypatch):
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **kw: None)

    root = tmp_path / "repos"
    _fixture_fleet(root)

    serial_state = tmp_path / "serial"
    parallel_state = tmp_path / "parallel"

    run_pipeline([root], str(serial_state), "2026-08-25",
                 run=_empty_engine, http=_no_network, jobs=1)
    run_pipeline([root], str(parallel_state), "2026-08-25",
                 run=_empty_engine, http=_no_network, jobs=4)

    for artifact in ("drift.json", "audit.json", "drift.md"):
        assert (serial_state / artifact).read_bytes() == (parallel_state / artifact).read_bytes(), \
            f"{artifact} differs between --jobs 1 and --jobs 4"

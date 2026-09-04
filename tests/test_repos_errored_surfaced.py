"""A repo the scanner could not read must be SAID, and a fleet where none could be read
must not exit 0.

`coverage["reposErrored"]` was recorded by the scan and then reached nothing a caller sees:
not drift.json, not drift.md, not the CLI banner, not the exit code — and `reposScanned`
counts errored repos too. So a run in which EVERY repo blew up still printed
`✓ scan+audit: 🔴 0 · 🟠 0` and exited 0: "cannot see" rendered identically to "clean",
the one collapse this project exists to refuse. `--jobs` makes it newly reachable, because
oversubscribing ast-grep can push repos past the engine's 600s timeout, which lands in
exactly this list.
"""
import subprocess

import pytest

from agent.cli import main


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


@pytest.fixture
def exploding(monkeypatch):
    """Make named repos raise inside the per-repo sweep, exactly as an engine timeout does."""
    import agent.inventory_scan as inv
    real = inv.scan_repo

    def make(*names):
        def scan_repo(abs_, name, *a, **kw):
            if name in names:
                raise RuntimeError("engine timed out after 600s")
            # `run --root` never exposes a way to inject `secrets_run`, and this file relies on
            # the real ast-grep binary — so stub gitleaks (not present in this sandbox) rather
            # than let the surviving repos hit the real binary. `kw["secrets_run"]` is already
            # present (inventory_scan.py's own call always names it) but None, so `setdefault`
            # would not touch it — override the falsy value explicitly instead.
            kw["secrets_run"] = kw.get("secrets_run") or (lambda args: "[]")
            return real(abs_, name, *a, **kw)
        monkeypatch.setattr(inv, "scan_repo", scan_repo)
    return make


def test_a_run_where_every_repo_errored_does_not_exit_zero(tmp_path, exploding, capsys):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    _git_init(root / "api", {"composer.json": '{"require": {"php": "^8.1"}}'})
    exploding("web", "api")

    rc = main(["run", "--root", str(root), "--state", str(tmp_path / "state"),
               "--now", "2026-08-25"])
    err = capsys.readouterr().err
    assert rc != 0, "every repo errored — that is 'couldn't verify', never a clean exit 0"
    assert rc == 4, "follow the 'scanned 0 repositories' precedent: exit 4"
    assert "errored" in err
    assert "NOT a clean result" in err


def test_some_repos_errored_is_reported_on_stderr_and_names_them(tmp_path, exploding, capsys):
    root = tmp_path / "repos"
    for name in ("web", "api", "ui"):
        _git_init(root / name, {"composer.json": '{"require": {"php": "^8.2"}}'})
    exploding("api")

    rc = main(["run", "--root", str(root), "--state", str(tmp_path / "state"),
               "--now", "2026-08-25"])
    err = capsys.readouterr().err
    assert rc == 0, "one bad repo out of three still delivers a report"
    assert "1 repo(s) errored" in err
    assert "api" in err
    assert "engine timed out" in err


def test_a_clean_run_says_nothing_about_errors(tmp_path, exploding, capsys):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    exploding()                       # nothing explodes

    rc = main(["run", "--root", str(root), "--state", str(tmp_path / "state"),
               "--now", "2026-08-25"])
    assert rc == 0
    assert "errored" not in capsys.readouterr().err

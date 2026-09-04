"""A repo whose secrets scan failed must be SAID — not silently rendered as `Secrets 0`.

`coverage["secretsErrors"]` was computed by inventory_scan.py's per-repo sweep and reached
nothing a caller sees: not run.py's returned dict, not the CLI banner, not stderr. In a
sandbox with no `gitleaks` binary (this one), every `run` reported `Secrets 0`, printed no
warning, and exited 0 — the exact "cannot see == clean" collapse this project exists to
refuse, just for the secrets signal instead of the whole repo. Mirrors
tests/test_repos_errored_surfaced.py's shape for `reposErrored`.
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
def secrets_failing(monkeypatch):
    """Force the secrets scan to fail, exactly as a missing/timed-out gitleaks does —
    injected the same way tests/test_repos_errored_surfaced.py's `exploding` fixture
    injects an engine failure, so this test's own pass/fail does not depend on whether
    gitleaks happens to be installed on the machine running the suite."""
    import agent.inventory_scan as inv
    real = inv.scan_repo

    def scan_repo(abs_, name, *a, **kw):
        kw["secrets_run"] = lambda args: (_ for _ in ()).throw(
            FileNotFoundError("gitleaks"))
        return real(abs_, name, *a, **kw)
    monkeypatch.setattr(inv, "scan_repo", scan_repo)


def test_a_missing_gitleaks_binary_is_warned_about_on_stderr(tmp_path, capsys,
                                                              secrets_failing):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})

    rc = main(["run", "--root", str(root), "--state", str(tmp_path / "state"),
               "--now", "2026-08-25"])
    err = capsys.readouterr().err
    assert rc == 0, ("a secrets-scan failure must not abort the run — ast-grep/CVE/EOL "
                     "results for the repo are still good")
    assert "secrets scan failed for 1 repo(s)" in err
    assert "web" in err
    assert "UNKNOWN, not zero" in err

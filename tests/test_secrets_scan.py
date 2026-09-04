import json
import subprocess
from pathlib import Path

import pytest

from agent.lib import secrets_scan
from agent.lib.secrets_scan import run_secrets_scan
from tests import gitleaks_fake

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_run_secrets_scan_invokes_gitleaks_and_normalizes_matches():
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return gitleaks_fake.canned(
            gitleaks_fake.hit("generic-api-key", "config/feedvisor.php", 5,
                              commit="a1b2c3d", fingerprint="a1b2c3d:config/feedvisor.php:generic-api-key:5"))

    res = run_secrets_scan("/repo", run=fake_run)
    assert seen["args"][0] == "gitleaks"
    assert "detect" in seen["args"]
    assert "/repo" in seen["args"]
    assert res["matches"] == [{
        "ruleId": "generic-api-key", "path": "config/feedvisor.php", "line": 5,
        "commit": "a1b2c3d", "fingerprint": "a1b2c3d:config/feedvisor.php:generic-api-key:5",
    }]
    assert res["errors"] == []


def test_run_secrets_scan_never_carries_the_matched_secret_text():
    """gitleaks' own JSON report includes `Secret`/`Match` fields with the live credential
    text. run_secrets_scan must drop them — the whole point of a finding is to say WHERE a
    secret is, never to make a second copy of it inside our own report."""
    def fake_run(args):
        return gitleaks_fake.canned(
            gitleaks_fake.hit("generic-api-key", "x.php", 1, secret="sk_live_abc123REDACTME"))

    res = run_secrets_scan("/repo", run=fake_run)
    dumped = json.dumps(res)
    assert "sk_live_abc123REDACTME" not in dumped


def test_run_secrets_scan_on_a_clean_repo_returns_no_matches():
    res = run_secrets_scan("/repo", run=lambda args: gitleaks_fake.EMPTY)
    assert res == {"matches": [], "errors": []}


def test_this_repos_own_gitleaksignore_documents_the_fixture_exclusion():
    """Prove the guard the bug it targets exists at all: without SOME exclusion mechanism,
    gitleaks scanning this repo's own tree would flag tests/fixtures/**'s intentionally-fake
    secrets on every self-scan in CI. gitleaks' own convention for that is a `.gitleaksignore`
    file at the scanned repo's root (it reads the file itself; nothing here needs to invoke it
    or know its format) — so the fix lives as a file, not as code, and this test locks in that
    the file exists and explains itself.

    It must NOT contain fabricated fingerprint lines: this sandbox has no gitleaks binary
    (confirmed in Task 1), so there is no way to compute this repo's *real* fingerprints here.
    Populating real `commit:file:rule:line` rows is follow-up work for whoever next runs
    gitleaks against this repo with a live binary.
    """
    ignore_file = _REPO_ROOT / ".gitleaksignore"
    assert ignore_file.exists(), (
        "expected a .gitleaksignore at the repo root — gitleaks reads it itself when "
        "scanning a repo whose root contains one"
    )

    text = ignore_file.read_text()
    assert "tests/fixtures" in text, "must document that it exists for this repo's own fixtures"

    non_comment_lines = [
        line for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert non_comment_lines == [], (
        "no real gitleaks scan has run against this repo (no binary in this sandbox), so this "
        "file must not contain fabricated fingerprint rows that only LOOK like real findings — "
        "got: " + repr(non_comment_lines)
    )


def test_run_secrets_scan_does_not_need_to_know_about_gitleaksignore(tmp_path):
    """The exclusion lives entirely in gitleaks' own behavior (it reads `.gitleaksignore` from
    the scanned repo's root itself) — run_secrets_scan does no path-filtering of its own, so its
    invocation must be byte-for-byte identical whether or not the target repo happens to have a
    `.gitleaksignore` file. This locks in the design decision so a future contributor doesn't
    "helpfully" bolt exclusion logic onto this module."""
    plain_repo = tmp_path / "plain"
    plain_repo.mkdir()
    ignored_repo = tmp_path / "with_ignore_file"
    ignored_repo.mkdir()
    (ignored_repo / ".gitleaksignore").write_text("deadbeef:some/file.py:generic-api-key:1\n")

    seen = {}

    def fake_run(args):
        seen["args"] = args
        return gitleaks_fake.EMPTY

    run_secrets_scan(str(plain_repo), run=fake_run)
    args_without_ignore_file = seen["args"]

    run_secrets_scan(str(ignored_repo), run=fake_run)
    args_with_ignore_file = seen["args"]

    # Same shape apart from the --source value itself.
    assert args_without_ignore_file == [
        a.replace(str(ignored_repo), str(plain_repo)) for a in args_with_ignore_file
    ]
    joined = " ".join(args_with_ignore_file)
    assert "gitleaksignore" not in joined.lower()


# ── the engine's own failures stay the engine's (fault isolation) ─────────────────
# A repo's ast-grep endpoints, manifests and CVEs are computed BEFORE gitleaks runs and are
# independent of it. If a missing/hanging gitleaks binary raises out of this module, the
# per-repo try/except in inventory_scan throws that whole repo's good results away and files
# it under reposErrored for a reason that has nothing to do with them. So the external process
# is this module's problem: it degrades to an ERROR on the secrets signal only — never a
# silent empty, never an exception.

def test_a_missing_gitleaks_binary_degrades_to_an_error_not_an_exception():
    def fake_run(args):
        raise FileNotFoundError(2, "No such file or directory", "gitleaks")

    res = run_secrets_scan("/repo", run=fake_run)
    assert res["matches"] == []
    assert len(res["errors"]) == 1
    assert res["errors"][0]["path"] == "/repo"
    assert "gitleaks" in res["errors"][0]["message"]


def test_a_generic_os_error_from_the_binary_degrades_to_an_error():
    def fake_run(args):
        raise OSError(13, "Permission denied")

    res = run_secrets_scan("/repo", run=fake_run)
    assert res["matches"] == []
    assert len(res["errors"]) == 1
    assert "Permission denied" in res["errors"][0]["message"]


def test_a_gitleaks_timeout_degrades_to_an_error_not_an_exception():
    def fake_run(args):
        raise subprocess.TimeoutExpired(cmd=args, timeout=300)

    res = run_secrets_scan("/repo", run=fake_run)
    assert res["matches"] == []
    assert len(res["errors"]) == 1
    assert "300" in res["errors"][0]["message"]


# ── a failed invocation is not "no secrets found" ─────────────────────────────────

class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_default_run_signals_a_non_zero_gitleaks_exit_rather_than_returning_empty_stdout(monkeypatch):
    """gitleaks on a directory it cannot scan (no .git — this tool explicitly supports plain
    code folders) exits non-zero with empty stdout. Discarding returncode/stderr turned that
    into `{"matches": [], "errors": []}` — a false 'clean', the one thing CLAUDE.md forbids."""
    monkeypatch.setattr(secrets_scan.subprocess, "run",
                        lambda *a, **k: _Proc(1, "", "failed to get git log: exit status 128"))
    with pytest.raises(subprocess.CalledProcessError) as exc:
        secrets_scan._default_run(["gitleaks", "detect"])
    assert exc.value.returncode == 1


def test_a_failed_gitleaks_run_reports_an_error_never_a_clean_empty_result(monkeypatch):
    monkeypatch.setattr(secrets_scan.subprocess, "run",
                        lambda *a, **k: _Proc(1, "", "failed to get git log: exit status 128"))
    res = run_secrets_scan("/repo")
    assert res["matches"] == []
    assert len(res["errors"]) == 1, "a failed gitleaks run must not read as 'no secrets found'"
    assert res["errors"][0]["path"] == "/repo"
    assert "failed to get git log" in res["errors"][0]["message"]


def test_finding_secrets_is_not_a_tool_error(monkeypatch):
    """`--exit-code 0` is passed deliberately (Task 1) so gitleaks FINDING secrets exits 0
    instead of its native 1. The non-zero guard must not undo that distinction: a successful
    run that found something is matches, not errors."""
    monkeypatch.setattr(secrets_scan.subprocess, "run",
                        lambda *a, **k: _Proc(0, gitleaks_fake.canned(
                            gitleaks_fake.hit("generic-api-key", "x.php", 1)), ""))
    res = run_secrets_scan("/repo")
    assert res["errors"] == []
    assert [m["ruleId"] for m in res["matches"]] == ["generic-api-key"]

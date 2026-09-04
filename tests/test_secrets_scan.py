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


def test_default_run_reads_the_report_from_a_real_temp_file(monkeypatch):
    """VERIFIED AGAINST A REAL BINARY, in this project's own container image:
    `--report-path /dev/stdout` silently produced ZERO bytes on a scan that found a real
    leak — no error, no log line, exit 0. A real temp file is the fix; this pins that
    `_default_run` actually asks gitleaks to write to one and reads it back, rather than
    trusting proc.stdout."""
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        idx = args.index("--report-path")
        seen["report_path"] = args[idx + 1]
        assert seen["report_path"] != "/dev/stdout"
        Path(seen["report_path"]).write_text(gitleaks_fake.canned(
            gitleaks_fake.hit("generic-api-key", "x.php", 1)))
        return _Proc(0, "", "")

    monkeypatch.setattr(secrets_scan.subprocess, "run", fake_run)
    out = secrets_scan._default_run(["gitleaks", "detect"])
    assert json.loads(out)[0]["RuleID"] == "generic-api-key"


def test_default_run_declares_the_repo_a_safe_git_directory_without_touching_global_config(
        monkeypatch):
    """VERIFIED AGAINST A REAL BINARY, in this project's own container image: gitleaks
    shells out to `git`, which refuses a repo it doesn't own ("detected dubious
    ownership") whenever the scanned tree's UID differs from the running process's —
    exactly a CI runner mounting a host-owned checkout into a container. git silently
    logs an ERR line and reports "0 commits scanned" / "no leaks found", exit 0 — a
    false clean. GIT_CONFIG_* env vars (git's own per-invocation mechanism, no global
    config file written) fix it; verified live against a real deliberately-broken-
    ownership repo before this test was written."""
    seen = {}

    def fake_run(args, **kwargs):
        seen["env"] = kwargs.get("env") or {}
        Path(args[args.index("--report-path") + 1]).write_text(gitleaks_fake.EMPTY)
        return _Proc(0, "", "")

    monkeypatch.setattr(secrets_scan.subprocess, "run", fake_run)
    secrets_scan._default_run(["gitleaks", "detect"])
    assert seen["env"].get("GIT_CONFIG_COUNT") == "1"
    assert seen["env"].get("GIT_CONFIG_KEY_0") == "safe.directory"
    assert seen["env"].get("GIT_CONFIG_VALUE_0") == "*"


def test_a_plain_folder_without_git_gets_the_no_git_flag(tmp_path):
    """VERIFIED AGAINST A REAL GITLEAKS 8.30.1 BINARY: `detect` on a directory with no
    `.git`, without `--no-git`, silently returns `[]` at exit 0 — no warning, no error,
    nothing. This scanner explicitly supports scanning a plain code folder (see
    tests/test_zero_repos_is_not_clean.py's PM-reported ingestion feature) — without this
    flag, secret detection provided ZERO signal for that entire use case and looked
    clean while doing it, which is worse than an error."""
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return gitleaks_fake.EMPTY

    run_secrets_scan(str(tmp_path), run=fake_run)          # tmp_path has no .git
    assert "--no-git" in seen["args"]


def test_a_real_git_repo_does_not_get_the_no_git_flag(tmp_path):
    """VERIFIED AGAINST A REAL BINARY: --no-git on an actual git repo silently drops
    HISTORY scanning — gitleaks' whole value-add over a plain grep (module docstring:
    "scans a repo's git history, not just the working tree"). Must only apply to a path
    that genuinely has no .git, never unconditionally."""
    (tmp_path / ".git").mkdir()
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return gitleaks_fake.EMPTY

    run_secrets_scan(str(tmp_path), run=fake_run)
    assert "--no-git" not in seen["args"]


def test_a_no_git_scans_absolute_file_path_is_normalized_to_repo_relative(tmp_path):
    """VERIFIED AGAINST A REAL BINARY: in --no-git mode, gitleaks' `File` field is
    reported relative to whatever --source was given — since repo_scan.py always passes
    an ABSOLUTE repo_abs, that means an absolute path leaking local filesystem structure
    into inventory.json/drift.json/GitLab issues, and disagreeing with git-mode
    gitleaks' own convention (always repo-relative, regardless of how --source was
    given). Normalize to repo-relative, matching every other path in this tool."""
    abs_path = str(tmp_path / "secret.php")

    def fake_run(args):
        return gitleaks_fake.canned(gitleaks_fake.hit("generic-api-key", abs_path, 5))

    res = run_secrets_scan(str(tmp_path), run=fake_run)
    assert res["matches"][0]["path"] == "secret.php"


def test_a_git_mode_relative_file_path_is_left_alone(tmp_path):
    """git-mode gitleaks already reports repo-relative paths regardless of --source —
    must not be mangled by relativizing a path that was never absolute."""
    (tmp_path / ".git").mkdir()

    def fake_run(args):
        return gitleaks_fake.canned(gitleaks_fake.hit("generic-api-key", "src/a.php", 5))

    res = run_secrets_scan(str(tmp_path), run=fake_run)
    assert res["matches"][0]["path"] == "src/a.php"


def test_resolve_gitleaks_finds_it_next_to_the_python_interpreter(tmp_path, monkeypatch):
    """Mirrors agent.lib.scan_util.resolve_engine's lookup for ast-grep: bin/drift-scan
    downloads gitleaks into the venv's bin/, next to the venv's python — a bare
    subprocess.run(["gitleaks", ...]) relying on PATH alone would never find it there."""
    monkeypatch.setattr(secrets_scan.shutil, "which", lambda name: None)
    fake_bin = tmp_path / "gitleaks"
    fake_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(secrets_scan.sys, "executable", str(tmp_path / "python"))
    assert secrets_scan._resolve_gitleaks() == str(fake_bin)


def test_resolve_gitleaks_prefers_path_over_the_venv(monkeypatch):
    monkeypatch.setattr(secrets_scan.shutil, "which", lambda name: "/usr/local/bin/gitleaks")
    assert secrets_scan._resolve_gitleaks() == "/usr/local/bin/gitleaks"


def test_resolve_gitleaks_falls_back_to_the_bare_name_when_not_found_anywhere(
        tmp_path, monkeypatch):
    """gitleaks is OPTIONAL (unlike ast-grep) — when it can't be found anywhere, this must
    still return a usable command, not raise. run_secrets_scan's own fault isolation turns
    the resulting FileNotFoundError into a per-repo secretsError, not a crashed scan."""
    monkeypatch.setattr(secrets_scan.shutil, "which", lambda name: None)
    monkeypatch.setattr(secrets_scan.sys, "executable", str(tmp_path / "python"))
    assert secrets_scan._resolve_gitleaks() == "gitleaks"


def test_run_secrets_scan_invokes_the_resolved_binary_path_not_a_bare_name(
        tmp_path, monkeypatch):
    fake_bin = tmp_path / "gitleaks"
    fake_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(secrets_scan, "_resolve_gitleaks", lambda: str(fake_bin))
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return gitleaks_fake.EMPTY

    run_secrets_scan("/repo", run=fake_run)
    assert seen["args"][0] == str(fake_bin)


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
    def fake_run(args, **k):
        # _default_run reads gitleaks' report back from a real temp file (VERIFIED
        # AGAINST A REAL BINARY: --report-path /dev/stdout produced nothing in this
        # project's own container image) — write the canned report to whatever path it
        # asked gitleaks to write to, standing in for gitleaks actually doing so.
        report_path = args[args.index("--report-path") + 1]
        Path(report_path).write_text(gitleaks_fake.canned(
            gitleaks_fake.hit("generic-api-key", "x.php", 1)))
        return _Proc(0, "", "")

    monkeypatch.setattr(secrets_scan.subprocess, "run", fake_run)
    res = run_secrets_scan("/repo")
    assert res["errors"] == []
    assert [m["ruleId"] for m in res["matches"]] == ["generic-api-key"]

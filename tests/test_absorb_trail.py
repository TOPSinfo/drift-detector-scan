"""The absorb trail: an append-only record of what each `absorb --check` attempt achieved.

The gate already computes a complete before/after per attempt and throws it away, so a session
leaves no evidence and an iterating agent cannot tell convergence from oscillation. This module
is the persistence, and these tests pin the properties that make it safe to add: it never raises
into the caller, and it never becomes something the certified path depends on.
"""
import json
import os

from agent.lib import absorb_trail


def _delta(attributed_after=44, problems=None):
    return {"attributedBefore": 0, "attributedAfter": attributed_after,
            "residueBefore": 51, "residueAfter": 7,
            "claims": {"met": ["a.php:1"], "missing": []},
            "invented": [], "unclaimed": [], "problems": problems or []}


def test_append_writes_one_line_per_attempt_numbered_in_order(tmp_path):
    for i in range(3):
        assert absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1"],
                                   delta=_delta(), now="2026-08-19") is True
    rows = absorb_trail.read(str(tmp_path))
    assert [r["attempt"] for r in rows] == [1, 2, 3]
    assert all(r["repo"] == "acme/api" for r in rows)


def test_attempt_numbering_is_per_repo_not_global(tmp_path):
    absorb_trail.append(str(tmp_path), repo="acme/one", staged=[], delta=_delta(), now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="acme/two", staged=[], delta=_delta(), now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="acme/one", staged=[], delta=_delta(), now="2026-08-19")
    assert [r["attempt"] for r in absorb_trail.read(str(tmp_path), repo="acme/one")] == [1, 2]
    assert [r["attempt"] for r in absorb_trail.read(str(tmp_path), repo="acme/two")] == [1]


def test_verdict_is_pass_only_when_there_are_no_problems(tmp_path):
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(problems=["bad"]),
                        now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(), now="2026-08-19")
    assert [r["verdict"] for r in absorb_trail.read(str(tmp_path))] == ["reject", "pass"]


def test_now_is_recorded_as_given_and_never_invented(tmp_path):
    # Determinism: `now` is passed in throughout this codebase. A trail that filled in the wall
    # clock would make the file unreproducible and quietly break that rule.
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(), now=None)
    assert absorb_trail.read(str(tmp_path))[0]["now"] is None


def test_append_returns_false_instead_of_raising_when_it_cannot_write(tmp_path):
    # THE BUG THIS GUARDS: a by-product may not break the product. If the trail cannot be
    # written, `absorb --check` must still report its verdict and exit code unchanged.
    unwritable = tmp_path / "nope"
    unwritable.write_text("i am a file, not a directory")
    assert absorb_trail.append(str(unwritable), repo="r", staged=[], delta=_delta(),
                               now="2026-08-19") is False


def test_read_ignores_a_corrupt_line_rather_than_dying(tmp_path):
    # A hand-edited or truncated trail is a debugging file, not a contract. Losing one line is
    # acceptable; refusing to render anything is not.
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(), now="2026-08-19")
    with open(os.path.join(str(tmp_path), absorb_trail.FILENAME), "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    assert len(absorb_trail.read(str(tmp_path))) == 1


def test_read_survives_a_line_with_invalid_utf8_bytes(tmp_path):
    # A process killed mid-write can truncate a multi-byte character, leaving a line that is not
    # valid UTF-8 at all. `for line in fh` decodes as it iterates, so that failure happens BEFORE
    # the per-line json.loads try — a UnicodeDecodeError, which is not an OSError and not caught
    # by read's outer `except OSError`. Tasks 3 and 4 call `read` directly (not through `append`,
    # which happens to catch ValueError and mask this), so this would crash the renderer on
    # exactly the corruption this module claims to tolerate.
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(), now="2026-08-19")
    with open(os.path.join(str(tmp_path), absorb_trail.FILENAME), "ab") as fh:
        fh.write(b"\xff\xfe not utf-8\n")
    assert len(absorb_trail.read(str(tmp_path))) == 1


def test_read_of_a_missing_trail_is_empty_not_an_error(tmp_path):
    assert absorb_trail.read(str(tmp_path)) == []


def test_the_written_line_carries_the_gate_delta_verbatim(tmp_path):
    d = _delta()
    absorb_trail.append(str(tmp_path), repo="r", staged=["i/1", "i/2"], delta=d, now="2026-08-19")
    row = absorb_trail.read(str(tmp_path))[0]
    assert row["delta"] == d, "the trail must record the gate's own numbers, not a re-derivation"
    assert row["staged"] == ["i/1", "i/2"]


def test_check_without_trail_writes_nothing(tmp_path, monkeypatch):
    """PURITY. `absorb --check` is documented as a dry run that writes nothing in TWO places —
    commands/drift-absorb.md and agent/absorb.py's docstring. The trail is opt-in precisely so
    that stays true; this pins it against a future change that makes writing the default."""
    from agent import cli
    calls = []
    monkeypatch.setattr(absorb_trail, "append", lambda *a, **k: calls.append(k) or True)
    args = _FakeArgs(state=str(tmp_path), trail=False)
    cli._maybe_record_trail(args, repo="r", staged=[], delta=_delta())
    assert calls == []
    assert not os.path.exists(os.path.join(str(tmp_path), absorb_trail.FILENAME))


def test_check_with_trail_records_one_row(tmp_path):
    from agent import cli
    args = _FakeArgs(state=str(tmp_path), trail=True, now="2026-08-19")
    cli._maybe_record_trail(args, repo="acme/api", staged=["i/1"], delta=_delta())
    rows = absorb_trail.read(str(tmp_path))
    assert len(rows) == 1 and rows[0]["repo"] == "acme/api" and rows[0]["attempt"] == 1


def test_trail_without_state_is_a_warning_not_a_crash(tmp_path, capsys):
    """--trail needs somewhere to write. Saying so beats writing nowhere silently."""
    from agent import cli
    args = _FakeArgs(state=None, trail=True)
    cli._maybe_record_trail(args, repo="r", staged=[], delta=_delta())
    assert "trail" in capsys.readouterr().err.lower()


class _FakeArgs:
    def __init__(self, **kw):
        self.state = kw.get("state")
        self.trail = kw.get("trail", False)
        self.now = kw.get("now")


def test_render_shows_each_attempt_as_a_row(tmp_path):
    absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1"],
                        delta=_delta(attributed_after=0, problems=["no claim met"]),
                        now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1", "i/2"],
                        delta=_delta(), now="2026-08-19")
    out = absorb_trail.render(absorb_trail.read(str(tmp_path)))
    assert "acme/api" in out
    assert "0 → 0" in out and "0 → 44" in out       # the climb is visible
    assert "reject" in out and "pass" in out
    assert "2 attempts" in out


def test_render_of_no_attempts_says_so_rather_than_looking_clean(tmp_path):
    # THE BUG THIS GUARDS: an empty table reads as "nothing went wrong". "No attempts recorded"
    # reads as what it is. This project's whole thesis is that absence must not look like health.
    out = absorb_trail.render([])
    assert "no attempts recorded" in out.lower()
    assert "|" not in out, "an empty table would imply a session that produced nothing to fix"


def test_forget_removes_only_the_named_repo(tmp_path):
    absorb_trail.append(str(tmp_path), repo="keep/me", staged=[], delta=_delta(), now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="drop/me", staged=[], delta=_delta(), now="2026-08-19")
    assert absorb_trail.forget(str(tmp_path), "drop/me") == 1
    remaining = absorb_trail.read(str(tmp_path))
    assert [r["repo"] for r in remaining] == ["keep/me"]


def test_forget_of_an_unknown_repo_removes_nothing(tmp_path):
    absorb_trail.append(str(tmp_path), repo="keep/me", staged=[], delta=_delta(), now="2026-08-19")
    assert absorb_trail.forget(str(tmp_path), "never/absorbed") == 0
    assert len(absorb_trail.read(str(tmp_path))) == 1


def test_render_escapes_a_pipe_in_a_problem_string(tmp_path):
    # THE BUG THIS GUARDS: absorb.py builds problem strings with `!r` over hand-edited YAML
    # scalars, which can contain a literal `|`. Dropped straight into a Markdown table cell, that
    # `|` opens a phantom column and misaligns the row.
    #
    # Parsed with the same unescaped-pipe splitter `verify.py` uses on drift.md (`_CELL_SPLIT`,
    # `(?<!\\)\|`) rather than a naive `str.split("|")` — a correctly-escaped `\|` is still two
    # characters, so a naive split would still (wrongly) treat it as a column break.
    from agent.lib.verify import _parse_md_tables

    absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1"],
                        delta=_delta(attributed_after=0, problems=["bad token: 'a|b'"]),
                        now="2026-08-19")
    out = absorb_trail.render(absorb_trail.read(str(tmp_path)))
    tables = _parse_md_tables(out)
    assert len(tables) == 1
    row = tables[0]["rows"][0]
    assert len(row) == len(tables[0]["header"]) == 6, \
        "an unescaped '|' in the problem string added a phantom column"
    assert row[-1] == "reject — bad token: 'a\\|b'"


def test_forget_returns_negative_one_instead_of_raising_when_it_cannot_write(tmp_path):
    # THE BUG THIS GUARDS: `append` and `read` both swallow OSError and degrade gracefully;
    # `forget` did not, so `absorb-report --forget` on an unwritable trail died with a raw
    # PermissionError traceback instead of reporting cleanly like the rest of this module.
    #
    # The trail file itself is made read-only (blocks the old `open(path, "w")` truncate) AND its
    # directory loses write permission (blocks creating the atomic-rewrite's temp file) — a
    # read-only mount would look like this. Either alone only fails one of the two
    # implementations; together they pin the target behaviour regardless of which write strategy
    # is in use.
    absorb_trail.append(str(tmp_path), repo="drop/me", staged=[], delta=_delta(), now="2026-08-19")
    trail_file = os.path.join(str(tmp_path), absorb_trail.FILENAME)
    os.chmod(trail_file, 0o444)
    os.chmod(str(tmp_path), 0o555)
    try:
        assert absorb_trail.forget(str(tmp_path), "drop/me") == -1
    finally:
        os.chmod(str(tmp_path), 0o755)  # restore so pytest can clean up tmp_path
        os.chmod(trail_file, 0o644)


def test_forget_leaves_kept_rows_intact_on_success(tmp_path):
    # Guards the atomic rewrite (temp file + os.replace): a crash mid-write of a plain "w" must
    # not lose rows for repos that should have been KEPT.
    absorb_trail.append(str(tmp_path), repo="keep/me", staged=["i/1"], delta=_delta(),
                        now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="keep/me", staged=["i/1", "i/2"], delta=_delta(),
                        now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="drop/me", staged=[], delta=_delta(), now="2026-08-19")
    assert absorb_trail.forget(str(tmp_path), "drop/me") == 1
    remaining = absorb_trail.read(str(tmp_path))
    assert [r["repo"] for r in remaining] == ["keep/me", "keep/me"]
    assert [r["attempt"] for r in remaining] == [1, 2]


def test_absorb_report_command_wires_read_render_stdout(tmp_path, capsys):
    # The tests above exercise `render` in isolation, against hand-built row lists. This one
    # drives the actual `absorb-report` CLI command — args -> read -> render -> stdout — so a
    # break in that wiring (wrong state dir, wrong kwarg, printing the wrong thing) fails here
    # even if `render` itself is correct.
    import types

    from agent import cli

    absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1"],
                        delta=_delta(attributed_after=0, problems=["no claim met"]),
                        now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="acme/api", staged=["i/1", "i/2"],
                        delta=_delta(), now="2026-08-19")
    args = types.SimpleNamespace(state=str(tmp_path), repo=None, forget=None)
    assert cli._cmd_absorb_report(args) == 0
    out = capsys.readouterr().out
    assert "acme/api" in out
    assert "0 → 0" in out and "0 → 44" in out


import subprocess


def test_the_trail_filename_is_gitignored(tmp_path):
    """It carries client file:line data and repo identities. Being gitignored is the mechanism
    that keeps it out of a public tree; a comment asking people to be careful is not."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(["git", "check-ignore", "-q", absorb_trail.FILENAME],
                         cwd=root).returncode
    assert out == 0, f"{absorb_trail.FILENAME} must be gitignored — it is client data"


def test_verify_does_not_read_the_trail():
    """BOUNDARY: a debugging by-product must never become something the correctness claim rests
    on. If verify learned to read the trail, deleting a debug file could change whether a report
    is judged correct."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "agent", "lib", "verify.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "absorb_trail" not in src and absorb_trail.FILENAME not in src


def test_absorb_report_resolves_a_directory_path_to_the_same_id_the_writer_used(tmp_path, capsys):
    # THE BUG THIS GUARDS: `_cmd_absorb` writes trail rows keyed on
    # scan_util.repo_scope_id(args.repo) — the git REMOTE url, falling back to the local path
    # only when there's no remote. But `_cmd_absorb_report` used to match the raw --repo /
    # --forget string VERBATIM, and the documented loop (commands/drift-absorb.md) passes a
    # FOLDER PATH as $REPO. So rows stored under "https://example.com/acme/api" were invisible
    # to `--repo <path-to-the-clone>`, and `--forget <path>` reported "removed 0 attempt(s)"
    # while leaving every row on disk — a client-data deletion control silently failing.
    #
    # test_absorb_report_command_wires_read_render_stdout (above) passes the SAME string on
    # both the write and the read side, which is exactly why it never caught this: it never
    # exercises the writer's path -> remote-url normalisation at all.
    import subprocess
    import types

    from agent import cli
    from agent.lib import scan_util

    repo_dir = tmp_path / "acme-api-clone"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@example.com:acme/api.git"],
                   cwd=str(repo_dir), check=True)

    state = tmp_path / "state"
    resolved_id = scan_util.repo_scope_id(str(repo_dir))
    assert resolved_id != str(repo_dir), "the fixture is only meaningful if resolution changes the id"

    record_args = types.SimpleNamespace(state=str(state), trail=True, now="2026-08-19")
    cli._maybe_record_trail(record_args, repo=resolved_id, staged=["i/1"], delta=_delta())
    assert absorb_trail.read(str(state))[0]["repo"] == resolved_id

    # --repo with the DIRECTORY PATH (as the documented loop passes it) must find the row.
    report_args = types.SimpleNamespace(state=str(state), repo=str(repo_dir), forget=None)
    assert cli._cmd_absorb_report(report_args) == 0
    out = capsys.readouterr().out
    assert "No attempts recorded" not in out
    assert "0 → 44" in out

    # --forget with the same DIRECTORY PATH must actually remove the row, not silently no-op.
    forget_args = types.SimpleNamespace(state=str(state), repo=None, forget=str(repo_dir))
    assert cli._cmd_absorb_report(forget_args) == 0
    assert absorb_trail.read(str(state)) == [], "the row must actually be gone, not merely reported gone"


def test_render_header_reflects_the_last_attempt_not_any_pass_ever(tmp_path):
    # THE BUG THIS GUARDS: the header used to be `any(a["verdict"] == "pass" for a in attempts)`,
    # so a reject -> pass -> reject sequence rendered "3 attempts, PASSED" — a proposal the gate
    # CURRENTLY rejects reading as passed at a glance. That is absence-looking-like-health, the
    # exact failure this project exists to prevent, in its own debug output.
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(problems=["p1"]),
                        now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(), now="2026-08-19")
    absorb_trail.append(str(tmp_path), repo="r", staged=[], delta=_delta(problems=["p2"]),
                        now="2026-08-19")
    out = absorb_trail.render(absorb_trail.read(str(tmp_path)))
    header_line = next(line for line in out.splitlines() if line.startswith("## r"))
    assert header_line.strip() != "## r — 3 attempts, PASSED", \
        "reject -> pass -> reject must not render as a bare PASSED header"
    assert "REJECT" in header_line.upper(), "the header must reflect the LAST attempt, which rejected"
    assert "2" in header_line, "the earlier pass (attempt #2) must still be visible, not hidden"


def test_absorb_report_forget_of_unrecorded_repo_says_so_explicitly(tmp_path, capsys):
    # THE BUG THIS GUARDS: `--forget` for an id with zero matching rows used to print
    # "absorb-report: removed 0 attempt(s) for <id>" and exit 0 — indistinguishable at a glance
    # from a successful prune. That is exactly how the Fix-1 identity mismatch went unnoticed: a
    # real prune FAILURE looked exactly like a real prune SUCCESS.
    import types

    from agent import cli

    absorb_trail.append(str(tmp_path), repo="acme/known", staged=[], delta=_delta(), now="2026-08-19")
    args = types.SimpleNamespace(state=str(tmp_path), repo=None, forget="acme/unknown")
    assert cli._cmd_absorb_report(args) == 0
    out = capsys.readouterr().out
    lower = out.lower()
    assert "nothing" in lower or "no match" in lower, \
        "a zero-row forget must say so explicitly, not read as a bare success"
    assert "acme/known" in out, "list the repo ids actually present, so the mismatch is visible"

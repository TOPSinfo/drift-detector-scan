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

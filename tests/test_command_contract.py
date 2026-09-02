"""The command file is the plugin's contract with the model. These are the parts of it that a
real session got wrong on 2026-09-02: the report was relayed whole with its front-matter, the
same vendors were stated three times, four absolute paths were printed, and the scanned repo's
own instruction files were read into the session."""
from pathlib import Path

CMD = Path(__file__).resolve().parents[1] / "commands" / "drift-detector.md"


def test_the_command_tells_the_model_to_emit_the_rendered_block():
    text = CMD.read_text()
    assert "chat-summary" in text, "the closing block exists and the command must invoke it"


def test_the_command_forbids_pasting_the_report_inline():
    # Assert the actual prohibition sentence, not just that some paste-related words appear
    # somewhere in the file — a rewording to "you MAY paste drift.md inline" would still
    # contain "paste" and "drift.md" but must fail this test.
    text = CMD.read_text()
    assert "Do not paste `drift.md` inline." in text


def test_the_command_forbids_reading_the_scanned_repos_instruction_files():
    # Assert the actual prohibition sentence, not just that the filenames are mentioned
    # somewhere — a rewording to "you MAY read CLAUDE.md and .claude/rules/**" would still
    # contain both filenames but must fail this test.
    text = CMD.read_text()
    assert "Never read the scanned repo's instruction files." in text
    assert (
        "CLAUDE.md`, `AGENTS.md`, `.claude/rules/**`,\n"
        "`.cursor/**`, `.cursorrules` and `.github/copilot-instructions.md`"
    ) in text


def test_the_command_sizes_progress_to_the_run():
    """One line before a 15-second scan; a background poll for a 26-minute one. A fixed interval
    is chatty on three repos and silent on fifty-two."""
    text = CMD.read_text()
    assert "--progress" in text
    assert "run_in_background" in text or "background" in text


def test_the_command_forbids_one_line_per_repo_progress():
    # Assert the actual prohibition sentence, not just that "repo" and "line" appear somewhere —
    # a rewording to "you MAY emit one line per repo" would still contain both words but must
    # fail this test.
    text = CMD.read_text()
    assert "Never one line per repo" in text

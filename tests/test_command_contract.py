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
    text = CMD.read_text().lower()
    assert "do not paste" in text or "never paste" in text


def test_the_command_forbids_reading_the_scanned_repos_instruction_files():
    text = CMD.read_text()
    assert "CLAUDE.md" in text and ".claude/rules" in text

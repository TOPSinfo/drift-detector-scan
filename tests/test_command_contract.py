"""The command file is the plugin's contract with the model. These are the parts of it that a
real session got wrong on 2026-09-02: the report was relayed whole with its front-matter, the
same vendors were stated three times, four absolute paths were printed, and the scanned repo's
own instruction files were read into the session."""
import re
from pathlib import Path

CMD = Path(__file__).resolve().parents[1] / "commands" / "drift-detector.md"

_STEP = re.compile(r"^(\d+)\. \*\*(.+?)\*\*")


def _flat():
    """The command file with every run of whitespace collapsed to one space.

    Asserted sentences must survive a Markdown reflow: a paragraph rewrapped at a different
    column is not a semantic change, but it moves the newlines and would break a raw substring
    check. Normalise first, then assert the whole sentence."""
    return " ".join(CMD.read_text().split())


def _delivery_steps():
    """`(number, bold title)` for each numbered step under '## Deliver the report', in FILE
    order — which is the order a model reading top-to-bottom will execute them in."""
    body = CMD.read_text().split("## Deliver the report", 1)[1].split("\n## ", 1)[0]
    return [(int(m.group(1)), m.group(2))
            for m in (_STEP.match(l) for l in body.splitlines()) if m]


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
    text = _flat()
    assert "Never read the scanned repo's instruction files." in text
    assert ("`CLAUDE.md`, `AGENTS.md`, `.claude/rules/**`, `.cursor/**`, `.cursorrules` and "
            "`.github/copilot-instructions.md`") in text


def test_the_command_sizes_progress_to_the_run():
    """One line before a 15-second scan; a background poll for a 26-minute one. A fixed interval
    is chatty on three repos and silent on fifty-two."""
    text = CMD.read_text()
    assert "--progress" in text
    assert "run_in_background" in text
    assert "poll its **output**" in text, "run_in_background has no stderr-only channel to poll"


def test_the_command_forbids_one_line_per_repo_progress():
    # Assert the actual prohibition sentence, not just that "repo" and "line" appear somewhere —
    # a rewording to "you MAY emit one line per repo" would still contain both words but must
    # fail this test.
    text = CMD.read_text()
    assert "Never one line per repo" in text


# ── where the output ends ────────────────────────────────────────────────────────────────────
# The 2026-09-02 branch left the delivery section contradicting itself: it declared the closing
# block "the last thing you say" and then told the model to add sentences and offer the
# dashboard AFTER it. It had also deleted the strongest anti-noise rule in the document. These
# pin the ordering and the rule so neither can drift back.


def test_the_closing_block_is_the_last_step_of_the_delivery_section():
    """A step that runs after the terminal block is a step that appends noise to it. The order
    is the contract: everything else first, the block last."""
    steps = _delivery_steps()
    assert steps, "the delivery section has no numbered steps to order"
    # Both orderings have to agree, because a model follows both: the labels a reader counts by,
    # and the position on the page a reader works down. Renumbering alone would otherwise let
    # the block sit above two steps while still calling itself the last one.
    nums = [n for n, _ in steps]
    assert nums == sorted(nums), f"the delivery steps are misnumbered: {steps}"
    assert "Emit the closing block" in steps[-1][1], (
        f"the closing block is not the final delivery step; steps are: {steps}")
    assert sum("Emit the closing block" in s for _, s in steps) == 1


def test_the_command_forbids_appending_anything_after_the_closing_block():
    """The deleted rule, restored. Polarity-aware: a reword to "you MAY offer follow-ups after
    the block" would still mention the block and must fail."""
    assert ("It is the last thing you say: do not re-summarise it, re-order it, put a headline "
            "above it, append next steps, or offer anything.") in _flat()


def test_the_command_keeps_the_evidence_for_why_the_output_must_end():
    """The rule without its reason is a rule someone deletes as fussy. This is why it exists."""
    text = _flat()
    assert "five further blocks, three of them asking him to decide something" in text
    assert "The output has to end where the answer ends." in text


def test_the_ai_tally_and_offers_are_placed_before_the_closing_block():
    """The AI plane still mandates a tally, a pointer and two offers. A terminal closing block
    with no stated slot for them is what left them nowhere to go."""
    assert ("This, and every offer below, is emitted **before** the closing block") in _flat()


def test_the_intake_menu_does_not_promise_a_report_pasted_in_chat():
    """local-only used to promise the paste that the delivery section now forbids."""
    text = _flat()
    assert "the files on disk, summarised in chat" in text
    assert "the report pasted in chat" not in text


def test_the_resolution_rescan_carries_the_progress_rule_too():
    """The re-scan is a second full scan of the same fleet. Attaching the progress rule only to
    the first run leaves the back half of the wall time silent."""
    assert "Same progress rule as the first run — this re-scan takes as long." in _flat()


def test_the_command_forbids_working_around_a_gate_refusal():
    """On 2026-09-02 the leads gate refused a batch and the model edited the evidence and
    resubmitted until it passed — turning a real API version into 'dated (see file:line)'. A gate
    that can be satisfied by degrading the evidence is not a gate. CLAUDE.md already says a
    refusal is a trust artifact; the command file never said it."""
    text = " ".join(CMD.read_text().split())
    assert "never work around a gate refusal" in text
    assert "Report the refusal" in text


def test_the_command_forbids_reframing_the_workaround_as_a_helpful_offer():
    """The rule above is satisfied by a model that reports the refusal accurately and then
    immediately offers to fix and resubmit — the same workaround wearing a question mark. Close
    the loophole: a refused finding is worth a new submission with its own evidence, never a
    patch to make the refused one pass."""
    text = " ".join(CMD.read_text().split())
    assert "Do not then offer to fix it and resubmit" in text
    assert "not a patch to make the refused one pass" in text


def test_the_ai_wait_has_the_same_progress_rule_as_the_scan():
    """The scan got a progress rule; the AI pass, which takes MINUTES, got none. The observed run
    filled the gap with five consecutive lines all saying 'still running' — the same noise the
    closing-block work removed from the tail, reappearing in the middle."""
    text = " ".join(CMD.read_text().split())
    assert "Same progress rule as a fleet scan" in text
    assert "Never narrate the wait" in text
    # The cadence alone is not the rule. The scan's version works because it has a real signal
    # (`⚙ [n/N]` on the CLI's own output) and a stop condition (the process exits); the AI wait
    # copied the cadence and the "position, not events" wording with neither, so a model complies
    # literally with "40s elapsed — agents still reading repos" at every doubling and emits
    # exactly the filler the rule was written to remove. Step 1 dispatches one agent per scanned
    # repo, so N is known before the wait starts: the line must carry that count, and the wait
    # must end on the last agent returning, not on the text going quiet.
    assert "Step 1 dispatches ONE AGENT PER SCANNED REPO, so N is known before the wait starts" \
        in text
    assert "[n/N] repos cross-checked" in text
    assert ("Stop when the last agent returns and `ai_results.json` is assembled, not when the "
            "text stops changing.") in text


def test_the_command_tells_the_agent_which_field_a_dated_version_goes_in():
    """The `version` exemption exists in the gate but nothing told the sub-agent to use it, so
    the true Amazon SP-API path `/feeds/2020-09-04/feeds/{feedId}` went in `endpoint` — and
    because the gate refuses the BATCH, one such lead destroyed four clean ones and wrote no
    `leads.json` at all. The accepted shape has to be stated where the JSON is specified."""
    text = _flat()
    assert "belongs in `version` and nowhere else" in text
    assert "`endpoint` must never carry a date" in text
    assert "refuses the ENTIRE submission" in text


def test_the_new_submission_rule_names_the_act_that_makes_it_new():
    """"A new submission with its own evidence" is satisfiable by re-dispatching the sub-agent and
    re-running `leads` with the refused field blanked — no document edited, nothing offered, and
    the model can call it new in good faith. The rule needs an operational test, not a label."""
    text = _flat()
    assert "going back to the source and reading it again" in text
    assert ("it never means retyping the same JSON with the refused field deleted or blanked"
            in text)

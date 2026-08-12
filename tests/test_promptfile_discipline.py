"""Structural discipline-eval of the command promptfiles.

The behavioral form of this — actually invoking the commands and grading the output — is
`claude plugin eval` (with an ablation baseline). That command is gated in early access, so until
it opens these run free in CI and catch the exact regression it would: a load-bearing discipline
instruction silently edited out of a promptfile. A promptfile's *behavior* is only as good as the
rules it still states; these pin the rules whose removal would quietly break the tool's honesty.

`/drift-detector`'s discipline is guarded in test_runner.py; `/drift-onboard`'s in test_onboard.py.
This file covers `/drift-research` — the loop most exposed to "just make up a plausible date," which
had no guard.
"""
from pathlib import Path

_CMD = Path(__file__).resolve().parent.parent / "commands"


def _research() -> str:
    return (_CMD / "drift-research.md").read_text()


def test_research_never_invents_or_borrows_a_date():
    t = _research()
    # the founding scar: no recalled/unfetched dates, and a blocked source is an honest 'unverified'
    assert "A date you did not fetch this session does not exist" in t
    assert "never a guess" in t
    assert "unverified" in t
    # a third-party page is NOT a source — the exact trap the UPS case exposed
    assert "not" in t and "a source" in t
    assert "blog" in t


def test_research_verbatim_date_gate_is_described():
    t = _research()
    assert "verbatim-date check" in t
    # the excerpt must be copied from the page, not paraphrased
    assert "excerpt" in t and "copied from the page" in t


def test_research_structured_source_first_method_present():
    t = _research()
    assert "structured source FIRST" in t
    # the cheap sources named before any rendering
    assert "RSS" in t and "changelog.md" in t and "GitHub docs mirror" in t


def test_research_reader_fallback_is_scoped_and_private_safe():
    t = _research()
    assert "r.jina.ai" in t                       # the no-dependency SPA fallback (not Playwright)
    assert "JS-only SPA" in t                      # only for a genuine SPA, not every page
    assert "never for anything private" in t       # the reader gets only PUBLIC docs URLs


def test_research_hands_evidence_to_the_gate_not_the_catalog():
    t = _research()
    # the whole loop's premise: propose to a gate, never write the catalog directly
    assert "research --apply" in t
    assert "absorb" in t
    assert "by: ai-research" in t                  # AI 'current' is a weaker, TTL'd provenance tier

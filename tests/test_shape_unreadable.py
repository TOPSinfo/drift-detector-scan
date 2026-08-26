"""A repo the scanner could not read must never report KNOWN.

REGRESSION, found on a real fleet and reproduced in tools/make_demo_fleet.py: `ops-runbooks`
holds a README and no code. The census finds no files, `signalCoverage` is empty, `verdict`
collects no reasons, and the repo reports KNOWN — "we looked, it's fine". Meanwhile
`design-tokens`, which HAS JavaScript but calls nothing, is honestly UNKNOWN. A repo we could
not read scored healthier than one we could.

`verdict`'s own comment already states the rule for the readable case — "we did not look
successfully; we merely looked. Saying KNOWN there is the lie of omission principle 1 forbids" —
but its `if coverage and …` guard skips the empty case entirely.

The PM-reported symptom is a default branch holding only a README, but the defect is wider: any
unreadable repo, for any reason, currently renders as a clean zero.
"""
from agent.lib import shapes


def test_a_repo_with_nothing_readable_is_unknown():
    v, reasons = shapes.verdict(0, {}, {}, modeled=0, unmodeled=0)
    assert v == "UNKNOWN", "a repo with no readable file reported KNOWN — 'cannot see' as 'clean'"
    assert shapes.NO_READABLE_SOURCE in reasons


def test_the_reason_names_what_happened_not_what_was_found():
    """`no-egress-signal` means 'read it, found no calls'. This one means 'there was nothing to
    read'. Collapsing them would lose the only distinction that matters to a reader."""
    _, reasons = shapes.verdict(0, {}, {}, modeled=0, unmodeled=0)
    assert reasons == [shapes.NO_READABLE_SOURCE], (
        f"expected exactly the unreadable reason, got {reasons}")


def test_a_repo_with_code_but_no_calls_keeps_its_own_reason():
    """The readable-but-quiet case must NOT be reclassified — it is already honest."""
    cov = {"javascript": ["sink", "url", "path-assembly"]}
    v, reasons = shapes.verdict(0, {}, cov, modeled=4, unmodeled=0)
    assert v == "UNKNOWN"
    assert shapes.NO_EGRESS_SIGNAL in reasons
    assert shapes.NO_READABLE_SOURCE not in reasons, (
        "a repo we DID read must not be labelled unreadable")


def test_a_repo_of_unmodeled_code_keeps_unmodeled_language():
    """Rust/Kotlin-only repos already have a reason. They are not 'nothing to read' — there is
    plenty to read, we just ship no rules for it. Two different problems, two different words."""
    v, reasons = shapes.verdict(0, {}, {}, modeled=0, unmodeled=12)
    assert v == "UNKNOWN"
    assert shapes.UNMODELED_LANGUAGE in reasons
    assert shapes.NO_READABLE_SOURCE not in reasons


def test_a_readable_repo_with_findings_is_still_known():
    """The guard must not make everything UNKNOWN."""
    cov = {"php": ["sink", "url", "path-assembly"]}
    v, reasons = shapes.verdict(3, {}, cov, modeled=9, unmodeled=0)
    assert v == "KNOWN", f"a normal repo was reclassified: {reasons}"


def test_omitting_the_file_counts_does_not_make_a_readable_repo_unreadable():
    """CONFOUND GUARD. `modeled`/`unmodeled` default to 0, so a first cut of this rule keyed on
    `total_files == 0` alone told every caller that passes only `coverage` that its repo was
    unreadable — nine existing tests, all of them describing repos with real content. Absence of
    the counts is not evidence of an empty repo; signal coverage is derived from the census, so a
    non-empty coverage means files were read."""
    cov = {"php": ["sink", "url", "path-assembly"]}
    v, reasons = shapes.verdict(12, {}, cov)          # no modeled/unmodeled passed, as callers do
    assert shapes.NO_READABLE_SOURCE not in reasons
    assert v == "KNOWN", f"a readable repo was called unreadable on a defaulted count: {reasons}"

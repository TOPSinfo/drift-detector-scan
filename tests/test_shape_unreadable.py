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
import pytest

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


# --- the same rule, asserted where a stale or hand-edited document gets caught ---------------
#
# It lives in two places on purpose. shapes.verdict is where the verdict is COMPUTED; verify is
# where a drift.json that disagrees with the contract is refused. Every published surface is a
# projection of that document, and a projection claiming a blind repo is fine is the one error a
# reader has no way to detect for themselves.

def _payload(verdict, reasons, languages):
    return {"shapes": [
        {"repo": "readme-only", "languages": languages,
         "verdict": verdict, "reasons": reasons}]}


def test_verify_refuses_a_document_calling_an_unreadable_repo_known():
    from agent.lib import verify
    with pytest.raises(verify.Violation) as exc:
        verify.check_unreadable_not_known(_payload("KNOWN", [], {}))
    assert "readme-only" in str(exc.value)


def test_verify_accepts_the_corrected_shape():
    from agent.lib import verify
    verify.check_unreadable_not_known(_payload("UNKNOWN", ["no-readable-source"], {}))


def test_verify_leaves_a_readable_known_repo_alone():
    """The invariant must key on 'no readable source', not on KNOWN."""
    from agent.lib import verify
    verify.check_unreadable_not_known(_payload("KNOWN", [], {"php": 4}))


def test_the_invariant_is_registered_and_not_merely_defined():
    """A check nobody runs is a comment. verify_payload is the one runner; assert membership
    there rather than trusting that it was wired up."""
    import inspect

    from agent.lib import verify
    src = inspect.getsource(verify.verify_payload)
    assert "check_unreadable_not_known" in src, (
        "the invariant exists but verify_payload never calls it, so `drift-scan verify` would "
        "pass a document it was written to refuse")


def test_the_invariant_reads_the_key_the_real_builder_emits():
    """ANTI-HOLLOW GUARD. The first cut of this check read `payload["coverage"]["shapes"]`, which
    no document has — the shapes list is top-level. It could never have fired in production, and
    the unit tests above passed anyway because their fixture copied the same wrong path.

    So the binding is asserted against a payload built by the real builder, not a dict written by
    the same hand that wrote the check."""
    from agent.lib import verify
    from agent.lib.dashboard_render import build_payload

    # The real pipeline shape: inventory_scan rolls each repo's `shape` into
    # coverage["shapes"], and build_payload lifts that to a TOP-LEVEL payload["shapes"].
    # Both hops are what the invariant depends on, so both are exercised here.
    shape = {"repo": "readme-only", "languages": {}, "verdict": "KNOWN", "reasons": []}
    inv = {"generated": "2026-08-26",
           "repos": [{"id": 1, "path": "readme-only", "endpoints": [], "sdks": [],
                      "shape": shape}],
           "coverage": {"shapes": [shape]}}
    payload = build_payload(inv, {"generated": "2026-08-26", "actions": []})
    assert payload.get("shapes"), (
        "build_payload emits no top-level `shapes` — the invariant's key path is wrong again")
    with pytest.raises(verify.Violation):
        verify.check_unreadable_not_known(payload)


def test_every_blind_repo_is_named_not_only_the_first():
    """`verify_payload` exists so a run reports every violation "in one pass instead of one per
    run" — its own words. This check raised on the FIRST offender, so a real fleet with five
    unreadable repos reported `✗ 1 invariant(s) violated` naming one of them. An operator fixes
    that repo, re-runs the scan, and is told about the next: five scans to learn what one should
    have said.

    Measured on the live fleet, 2026-08-27: five repos were KNOWN with no readable source and
    verify named only one of them.
    """
    from agent.lib import verify

    payload = {"shapes": [
        {"repo": "alpha", "languages": {}, "verdict": "KNOWN"},
        {"repo": "beta", "languages": {"php": 3}, "verdict": "KNOWN"},   # readable, fine
        {"repo": "gamma", "languages": {}, "verdict": "KNOWN"},
        {"repo": "delta", "languages": {}, "verdict": "UNKNOWN"},        # already honest
    ]}
    with pytest.raises(verify.Violation) as exc:
        verify.check_unreadable_not_known(payload)

    msg = str(exc.value)
    assert "alpha" in msg and "gamma" in msg, f"not every blind repo was named:\n{msg}"
    assert "beta" not in msg and "delta" not in msg, f"a readable or honest repo was named:\n{msg}"

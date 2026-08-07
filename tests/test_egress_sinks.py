"""Every language that CLAIMS egress coverage must actually detect an outbound call.

Seven of eight languages had no egress rules, so `shapes.verdict()` returned
UNKNOWN/no-egress-signal for anything not PHP. Adding rules closes that — but a rule that
matches nothing is worse than no rule, because `rule_kinds_by_language()` would then
report `sink` coverage the scanner does not have, and a repo would grade KNOWN on the
strength of a rule that never fires. Silent blindness dressed as confidence is the exact
failure this project keeps having.

So this runs the REAL generated ruleset through the REAL engine against a fixture in each
language, and requires a hit. It is the only test here that needs the engine; it skips
rather than lying if the binary is absent.
"""
import os

import pytest

from agent.lib import engine as engine_mod
from agent.lib import scan_util
from agent.lib.vendor_rules import EGRESS_SINKS, write_ruleset
from agent.lib.vendors import load_vendors

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "egress")

# language -> the fixture proving that language's sinks fire
CASES = [
    ("php", "s.php"), ("javascript", "s.js"), ("typescript", "s.ts"),
    ("python", "s.py"), ("go", "s.go"), ("ruby", "s.rb"),
    ("java", "s.java"), ("csharp", "s.cs"),
]


@pytest.fixture(scope="module")
def ruleset(tmp_path_factory):
    try:
        engine = scan_util.resolve_engine()
    except RuntimeError:
        pytest.skip("ast-grep not installed — cannot verify rules actually fire")
    path = str(tmp_path_factory.mktemp("rules") / "rules.yaml")
    write_ruleset(load_vendors(), path)
    return engine, path


@pytest.mark.parametrize("language,fixture", CASES)
def test_every_language_detects_an_outbound_call(language, fixture, ruleset):
    """A `sink` match on a file that plainly makes an HTTP call."""
    engine, rules = ruleset
    out = engine_mod.run_scan(FIXTURES, rules, engine=engine)
    sinks = [m for m in out["matches"]
             if m.get("kind") == "sink" and m.get("path", "").endswith(fixture)]
    assert sinks, (
        f"{language}: the ruleset claims `sink` coverage but matched nothing in "
        f"{fixture}, which makes an outbound HTTP call on almost every line. "
        f"rule_kinds_by_language() would report coverage this scanner does not have.")


def test_no_language_claims_coverage_it_cannot_deliver():
    """Guards the pairing itself: a language added to EGRESS_SINKS without a fixture
    would claim `sink` coverage that nothing here ever exercises."""
    covered = set(EGRESS_SINKS)
    tested = {lang for lang, _ in CASES}
    assert covered == tested, (
        f"languages in EGRESS_SINKS but never proven to fire: {sorted(covered - tested)}; "
        f"tested but not declared: {sorted(tested - covered)}")


def test_deliberately_excluded_patterns_stay_excluded():
    """Noisy matchers were rejected on purpose; re-adding one should be a decision, not
    a drift. `$C.Do($$$)` in Go matches sync.Once.Do and every builder .Do() there is."""
    flat = repr(EGRESS_SINKS)
    assert "$C.Do(" not in flat, "Go $C.Do matches sync.Once.Do — too noisy to be a sink"
    assert "file_get_contents" not in flat, "PHP file_get_contents is usually filesystem"
    assert "got($$$)" not in flat, "`got` is a single common word, too easily shadowed"

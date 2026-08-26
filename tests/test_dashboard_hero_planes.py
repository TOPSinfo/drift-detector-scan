"""Every value `heroMode` can return must have its own branch in the hero panel.

REGRESSION. `heroMode` returns "supply" for the Supply Chain plane, but the template carried no
`v-else-if` for it, so that plane fell through to the AI Frontier catch-all — and a plane listing
dozens of CVE rows was captioned *"Nothing in this dimension for the current scan."*

That is the inverse of CLAUDE.md principle 1. The principle exists to stop the tool rendering
"clean" when it means "could not see"; here it rendered "found nothing" directly above a table of
findings, which is the same collapse pointed the other way. `heroMode`'s own comment already said
so — it falls back to the timeline "rather than lying with a 'nothing found' empty-state over a
tab that plainly has rows in the table below" — but nothing enforced it.

The guard is deliberately general rather than a string match on "supply": a plane added later with
no hero branch fails here, which is the shape the defect actually took.

Pure text analysis of the committed assets. No rendering, no browser, no network.
"""
from __future__ import annotations

import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "agent" / "assets"
APP = ASSETS / "dashboard.app.js"
TEMPLATE = ASSETS / "dashboard.template.html"

# The one mode that is allowed to have no branch of its own: it IS the catch-all `v-else`,
# and its copy ("Nothing in this dimension for the current scan") is only correct for a
# dimension that really is empty.
CATCH_ALL = "empty"


def _hero_modes() -> set[str]:
    """The string literals `heroMode` can return, read from its own return statements.

    Only `return` statements are scanned: the function also compares against tab names
    ("apis", "unknown") in its conditions, and those are not modes.
    """
    src = APP.read_text(encoding="utf-8")
    start = src.index("heroMode: function()")
    end = src.index("heroTitle: function()", start)   # the next sibling computed
    body = src[start:end]
    modes: set[str] = set()
    for stmt in re.findall(r"return\s+([^;]+);", body):
        modes |= set(re.findall(r'"([a-z]+)"', stmt))
    return modes


def _branched_modes() -> set[str]:
    """The modes the hero panel actually tests for."""
    return set(re.findall(r"heroMode === '([a-z]+)'", TEMPLATE.read_text(encoding="utf-8")))


def test_every_hero_mode_has_its_own_branch():
    modes = _hero_modes()
    assert modes, "could not parse heroMode's return values — the guard would pass vacuously"
    missing = modes - _branched_modes() - {CATCH_ALL}
    assert not missing, (
        f"heroMode can return {sorted(missing)} but the hero panel has no branch for it, so that "
        f"plane falls through to the catch-all empty-state and captions its findings 'Nothing in "
        f"this dimension for the current scan'. Give it a branch, or make the empty-state "
        f"conditional on the dimension actually being empty.")


def test_supply_is_the_specific_plane_this_was_written_against():
    """Named explicitly so the regression cannot be 'fixed' by deleting the general test."""
    assert "supply" in _hero_modes(), "heroMode no longer returns 'supply' — retire this test"
    assert "supply" in _branched_modes(), (
        "the Supply Chain plane lost its hero branch again — it will caption CVE findings "
        "'Nothing in this dimension for the current scan'")


def test_the_empty_state_copy_is_not_reachable_with_findings_present():
    """The supply branch must guard its empty-state on the counts, not render it unconditionally."""
    src = TEMPLATE.read_text(encoding="utf-8")
    branch = src[src.index("heroMode === 'supply'"):]
    branch = branch[:branch.index("</template>")]
    assert "Nothing in this dimension" in branch, "the honest zero-state should still exist"
    assert re.search(r'v-else', branch), (
        "the supply branch renders its empty-state unconditionally — a zero-state that shows "
        "regardless of the counts is the original defect wearing a different tag")

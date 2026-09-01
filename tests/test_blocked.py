"""The access work-order — the vendors nobody here can audit, whatever they do.

BLOCKED is the one verdict `freshness.due_for_refresh` deliberately drops, and the reasoning is
right: re-reading a page behind a partner login cannot clear it, so listing it as research work
would keep that queue permanently non-empty, and a list that is never empty stops being read.

But the code that drops it also says how it clears — "only when someone supplies access" — and
until this module that actor had no surface at all. The blind spot was visible in a table inside
the report and nowhere else. This is the other audience: not the researcher, the person who can
obtain an account, a credential, or an allow-list entry.
"""
from agent.lib import blocked


def _rec(vendor, verdict, sites, why="", checked=""):
    r = {"vendor": vendor, "verdict": verdict, "callSites": sites, "checked": checked}
    if verdict == "BLOCKED":
        r["blocked"] = why
    return r


def test_only_blocked_records_are_selected():
    """UNAUDITED is research work and belongs to the freshness work-order. Mixing them would put
    tasks nobody outside can help with in front of the one person who can."""
    recs = [_rec("Mirakl", "BLOCKED", 25, "portal is account-gated"),
            _rec("UPS", "UNAUDITED", 35),
            _rec("Adyen", "CURRENT", 10),
            _rec("Temu", "BLOCKED", 1, "Seller Center requires an account")]
    assert [r["vendor"] for r in blocked.records(recs)] == ["Mirakl", "Temu"]


def test_records_are_ordered_by_exposure():
    """Call sites are the only ranking that means anything to someone deciding what access to
    chase first."""
    recs = [_rec("Temu", "BLOCKED", 1, "account"),
            _rec("Mirakl", "BLOCKED", 25, "gated"),
            _rec("Virtualstock", "BLOCKED", 24, "no portal")]
    assert [r["vendor"] for r in blocked.records(recs)] == ["Mirakl", "Virtualstock", "Temu"]


def test_the_body_names_the_vendor_its_exposure_and_what_would_unblock_it():
    """Each of the three is load-bearing: WHO to chase, HOW MUCH it is worth, and WHAT to get.
    A list of vendor names alone would send someone back to the report to find out why."""
    body = blocked.work_order_md(
        [_rec("Mirakl", "BLOCKED", 25, "documentation portal is account-gated", "2026-08-21")],
        now="2026-09-01")
    assert "Mirakl" in body
    assert "25" in body
    assert "documentation portal is account-gated" in body
    assert "2026-08-21" in body                      # when it was last attempted


def test_an_empty_list_says_so_plainly_so_the_work_order_can_close():
    """Mirrors freshness.work_order_md: the stream closes itself when there is nothing to do."""
    body = blocked.work_order_md([], now="2026-09-01")
    assert "Nothing" in body or "nothing" in body


def test_the_body_does_not_send_the_reader_to_drift_refresh():
    """The whole point of splitting this stream out. /drift-refresh re-reads a page — and the
    page cannot be read, which is why these are here. Telling an admin to run it wastes the one
    action that would actually work, and re-running it forever is how the freshness queue would
    have filled with permanently-failing tasks."""
    body = blocked.work_order_md(
        [_rec("Temu", "BLOCKED", 1, "Seller Center requires an account", "2026-08-21")],
        now="2026-09-01")
    assert "/drift-refresh" not in body


def test_zero_findings_is_never_presented_as_clean():
    """The product's cardinal rule, and the reason this stream exists at all: an unread
    retirement list is a blind spot, not a clean bill."""
    body = blocked.work_order_md(
        [_rec("Virtualstock", "BLOCKED", 24, "no public developer portal", "2026-08-21")],
        now="2026-09-01")
    low = body.lower()
    assert "not a clean" in low or "blind spot" in low

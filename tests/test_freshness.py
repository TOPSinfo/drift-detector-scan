"""The maintainer freshness work-order — pure, deterministic, no I/O."""
from agent.lib import freshness


_AUTO = {"eBay", "Shopify"}
_UNAUTO = {"Amazon SP-API": "run `drift-scan catalog-refresh --vendor \"Amazon SP-API\"`"}


def _cov(vendor, verdict, sites=1, checked=None, source=""):
    return {"vendor": vendor, "verdict": verdict, "callSites": sites,
            "checked": checked, "source": source, "reasons": []}


def test_current_and_auto_vendors_are_not_due():
    records = [_cov("eBay", "STALE"),            # auto lane → catalog_check handles it
               _cov("Shopify", "UNAUDITED"),     # auto lane
               _cov("MyDeal", "CURRENT")]        # freshly checked
    assert freshness.due_for_refresh(records, _AUTO, _UNAUTO) == []


def test_gated_marketplace_is_a_portal_action_with_verified_source():
    due = freshness.due_for_refresh([_cov("THE ICONIC", "UNAUDITED", 5)], _AUTO, _UNAUTO)
    assert len(due) == 1 and due[0]["action"] == freshness.PORTAL
    assert "theiconic.com.au" in due[0]["recipeSource"]


def test_public_vendor_is_NOT_told_to_log_into_a_portal():
    """The bug this guards: a public-docs vendor (AWS, Google) must not be mis-instructed to
    'log into the seller portal' — it has public deprecation docs, no login."""
    due = freshness.due_for_refresh([_cov("Amazon AWS", "UNAUDITED", 5),
                                     _cov("Google APIs", "UNAUDITED", 4)], _AUTO, _UNAUTO)
    assert all(r["action"] == freshness.PUBLIC for r in due)
    md = freshness.work_order_md(due, "2026-07-29")
    assert "Amazon AWS" in md and "log into the seller portal" not in md


def test_unmapped_vendor_says_find_where_it_publishes_not_portal():
    due = freshness.due_for_refresh([_cov("SomeNewVendor", "UNAUDITED")], _AUTO, _UNAUTO)
    assert due[0]["action"] == freshness.UNMAPPED
    assert "not yet mapped" in freshness.work_order_md(due, "2026-07-29")


def test_cli_vendor_gets_the_command_hint():
    due = freshness.due_for_refresh([_cov("Amazon SP-API", "STALE")], _AUTO, _UNAUTO)
    assert due[0]["action"] == freshness.CLI
    assert "catalog-refresh" in freshness.work_order_md(due, "2026-07-29")


def test_work_order_groups_by_action_and_names_the_gate():
    due = freshness.due_for_refresh(
        [_cov("MyDeal", "UNAUDITED", 3), _cov("Amazon AWS", "UNAUDITED", 5),
         _cov("Amazon SP-API", "STALE", 9)], _AUTO, _UNAUTO)
    md = freshness.work_order_md(due, "2026-07-29")
    assert "Behind a login — needs you (HIL)" in md and "MyDeal" in md
    assert "Public docs — no login" in md and "Amazon AWS" in md
    assert "A command away" in md and "Amazon SP-API" in md
    assert "/drift-refresh" in md and "absorb" in md and "attests the vendor **CURRENT**" in md


def test_nothing_due_says_so():
    assert "Nothing due" in freshness.work_order_md([], "2026-07-29")


def test_output_is_byte_identical():
    due = freshness.due_for_refresh([_cov("MyDeal", "UNAUDITED")], _AUTO, _UNAUTO)
    assert freshness.work_order_md(due, "2026-07-29") == freshness.work_order_md(due, "2026-07-29")

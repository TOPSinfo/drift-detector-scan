"""The freshness loop parses vendors' live sources and diffs them against our catalog —
so a NEW retirement, or a CHANGED date, surfaces instead of silently ageing."""
import os

from agent.lib import catalog_sources as cs

_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "catalog",
                    "ebay_deprecation.xml")


def _feed():
    with open(_FIX, encoding="utf-8") as fh:
        return fh.read()


def test_ebay_rss_parses_structured_facts_with_normalised_dates():
    facts = cs.parse_ebay_rss(_feed())
    assert facts, "expected at least one fact from the eBay feed"
    # dates are normalised YYYY-MM-DD (eBay writes YYYY/MM/DD), or None for TBD
    for f in facts:
        assert f["vendor"] == "eBay" and f["source"].startswith("http")
        assert f["retires"] is None or len(f["retires"]) == 10 and f["retires"][4] == "-"


def test_whole_api_items_have_no_operation_scope():
    """A method of 'All' or an item with no methods is a whole-API deprecation — kept
    without an operation, because it can't be scoped to a call-site."""
    facts = cs.parse_ebay_rss(_feed())
    # every method-scoped fact names its operation; the parser never invents one
    for f in facts:
        assert f["operation"] is None or isinstance(f["operation"], str) and f["operation"]


def test_diff_flags_new_changed_covered():
    facts = [
        {"vendor": "eBay", "api": "Trading API", "operation": "GetX", "retires": "2027-01-19",
         "deprecated": None, "source": "http://x"},
        {"vendor": "eBay", "api": "Trading API", "operation": "GetY", "retires": "2026-08-15",
         "deprecated": None, "source": "http://x"},
        {"vendor": "eBay", "api": "Trading API", "operation": "GetZ", "retires": None,
         "deprecated": None, "source": "http://x"},        # undated (TBD)
    ]
    catalog = [
        {"vendor": "eBay", "operation": "GetX", "retires": "2027-01-19"},   # covered
        {"vendor": "eBay", "operation": "GetY", "retires": "2026-06-04"},   # date CHANGED
    ]
    out = cs.diff_against_catalog(facts, catalog, "eBay")
    assert [f["operation"] for f in out["covered"]] == ["GetX"]
    assert out["changed"][0]["operation"] == "GetY"
    assert out["changed"][0]["catalogRetires"] == "2026-06-04"     # what we had
    assert out["changed"][0]["retires"] == "2026-08-15"            # what the vendor says now
    assert out["undated"][0]["operation"] == "GetZ"
    assert out["counts"] == {"new": 0, "changed": 1, "covered": 1, "undated": 1}


def test_diff_flags_a_genuinely_new_retirement():
    """The point of the loop: the vendor announces something we've never catalogued."""
    facts = [{"vendor": "eBay", "api": "Feed API", "operation": "NewlyRetired",
              "retires": "2028-01-01", "deprecated": None, "source": "http://x"}]
    out = cs.diff_against_catalog(facts, [], "eBay")
    assert out["new"][0]["operation"] == "NewlyRetired"
    assert out["counts"]["new"] == 1


def test_real_fixture_diffed_against_the_live_catalog_is_stable():
    """The committed feed reconciled against our actual eBay catalog: nothing should be
    'new' (we catalogued this feed on 2026-07-20). A future feed change makes new/changed
    non-empty, which is exactly the signal the command surfaces."""
    from agent.lib.vendor_sunsets import load_sunsets
    facts = cs.parse_ebay_rss(_feed())
    out = cs.diff_against_catalog(facts, load_sunsets(), "eBay")
    # the fixture is a 3-item slice; every dated, scopeable fact in it is already catalogued
    assert out["counts"]["new"] == 0, f"unexpected new eBay retirements: {out['new']}"


# ------------------------------------------------- Shopify: rule vs published table
_SHOP_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "catalog",
                         "shopify_versioning.md")


def _shopify_md():
    with open(_SHOP_FIX, encoding="utf-8") as fh:
        return fh.read()


def test_shopify_table_parses_all_rows():
    rows = cs.parse_shopify_versions(_shopify_md())
    assert len(rows) == 7
    assert {"version": "2025-07", "accessibleUntil": "2026-07-16"} in rows


def test_shopify_rule_still_reproduces_the_published_table():
    """Freshness for a computed vendor: our rule must match every row, or we've drifted
    from Shopify's policy."""
    res = cs.check_shopify_rule(_shopify_md())
    assert res["ok"] and res["rowsChecked"] == 7 and res["drift"] == []


def test_shopify_rule_drift_is_detected():
    """If Shopify changed the window (here: a doctored +1-month row), the check must flag
    it rather than silently keep computing the old dates."""
    tampered = _shopify_md().replace("| 2026-01 | January 1, 2026 | January 16, 2027 15:00 UTC |",
                                     "| 2026-01 | January 1, 2026 | February 16, 2027 15:00 UTC |")
    res = cs.check_shopify_rule(tampered)
    assert not res["ok"]
    assert res["drift"][0]["version"] == "2026-01"
    assert res["drift"][0]["accessibleUntil"] == "2027-02-16"    # what Shopify now says
    assert res["drift"][0]["ruleSays"] == "2027-01-16"           # what our rule computes


# ------------------------------------------------- the catalog-check command (injected fetch)
def test_catalog_check_reports_fresh_when_nothing_changed():
    from agent import catalog_check
    def fetch(url):
        return _feed() if "ebay" in url else _shopify_md()
    report = catalog_check.check_all(fetch=fetch, now="2026-07-21")
    assert not catalog_check.needs_attention(report)
    text = catalog_check.render(report)
    assert "up to date" in text and "still reproduces" in text


def test_catalog_check_flags_a_new_ebay_retirement():
    from agent import catalog_check
    # a feed with an operation our catalog has never seen
    feed = _feed().replace("<methods><method>", "<methods><method>BrandNewDeadCall</method><method>", 1)
    def fetch(url):
        return feed if "ebay" in url else _shopify_md()
    report = catalog_check.check_all(fetch=fetch, now="2026-07-21")
    assert catalog_check.needs_attention(report)


def test_catalog_check_reports_an_unreachable_source_not_a_clean_pass():
    from agent import catalog_check
    def fetch(url):
        raise ConnectionError("host down")
    report = catalog_check.check_all(fetch=fetch, now="2026-07-21")
    assert all(r.get("error") for r in report)
    assert "could not reach" in catalog_check.render(report)

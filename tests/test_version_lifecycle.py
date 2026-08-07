"""Shopify sunset dates are COMPUTED from the published rule — and the rule must
reproduce the vendor's own table exactly, or the computation is wrong."""
import pytest

from agent.lib import version_lifecycle as vl


# The authoritative cross-check: every row of Shopify's published support table, fetched
# 2026-07-21 from https://shopify.dev/docs/api/usage/versioning.md. The rule must land on
# each of these dates exactly — that is what licenses computing the rest.
PUBLISHED = {
    "2025-07": "2026-07-16",
    "2025-10": "2026-10-16",
    "2026-01": "2027-01-16",
    "2026-04": "2027-04-16",
    "2026-07": "2027-07-16",
    "2026-10": "2027-10-16",
    "2027-01": "2028-01-16",
}


@pytest.mark.parametrize("version,expected", PUBLISHED.items())
def test_rule_reproduces_the_published_table(version, expected):
    assert vl.shopify_sunset(version) == expected


def test_rule_extends_to_versions_beyond_the_table():
    """The point of a computed feeder: a version the table never listed still gets a
    date, so the catalog does not go stale or miss old versions."""
    assert vl.shopify_sunset("2024-01") == "2025-01-16"   # long dead
    assert vl.shopify_sunset("2030-04") == "2031-04-16"   # far future


def test_non_shopify_version_strings_are_rejected():
    for bad in ("v0", "2024-13", "2024", "2024-01-01", "", None, "latest"):
        assert vl.shopify_sunset(bad) is None


def test_lifecycle_sunset_only_fires_for_a_vendor_with_a_rule():
    assert vl.lifecycle_sunset("Amazon SP-API", "v0") is None      # no rule
    got = vl.lifecycle_sunset("Shopify", "2024-01")
    assert got["retires"] == "2025-01-16"
    assert got["source"] == vl.SHOPIFY_SOURCE
    assert "falls" in got["replacement"] or "silently serves" in got["replacement"]


def test_lifecycle_sunset_none_when_version_not_datable():
    assert vl.lifecycle_sunset("Shopify", "v1") is None


# ------------------------------------------------- integration through the audit
def test_audit_emits_computed_shopify_findings():
    """A doc with Shopify endpoints yields one sunset finding per version, dated by the
    rule — no catalog entry required."""
    from agent.audit import audit_inventory
    doc = {"generated": "2026-07-21", "repos": [{"path": "shop", "sdks": [], "endpoints": [
        {"vendor": "Shopify", "domain": "acme.myshopify.com", "version": "2024-01",
         "classified": True, "files": ["app/C.php:3"], "file_count": 1},
        {"vendor": "Shopify", "domain": "acme.myshopify.com", "version": "2026-04",
         "classified": True, "files": ["app/C.php:5"], "file_count": 1},
    ]}]}
    # offline: no OSV/EOL network needed for a Shopify-only doc
    audit = audit_inventory(doc, "2026-07-21", http=lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    shop = [f for f in audit["findings"] if f.get("ref") == "Shopify"]
    by_ver = {f["version"]: f for f in shop}
    assert by_ver["2024-01"]["date"] == "2025-01-16" and by_ver["2024-01"]["status"] == "DEPRECATED"
    assert by_ver["2026-04"]["date"] == "2027-04-16" and by_ver["2026-04"]["status"] == "REVIEW"
    # sourced to the rule page, never an invented per-version date
    assert all("shopify.dev" in f["source_url"] for f in shop)

from agent.lib import eol


_PHP = [
    {"cycle": "8.3", "eol": "2027-11-23", "latest": "8.3.10"},
    {"cycle": "8.2", "eol": "2026-12-31", "latest": "8.2.20"},
    {"cycle": "7.4", "eol": "2022-11-28", "latest": "7.4.33"},
]
_NODE = [
    {"cycle": "22", "eol": "2027-04-30", "latest": "22.5.0"},
    {"cycle": "15", "eol": "2021-06-01", "latest": "15.14.0"},
]


def _http(products):
    def h(url, *, method="GET", body=None, timeout=20):
        for slug, data in products.items():
            if f"/{slug}.json" in url:
                return data
        raise AssertionError("unexpected url " + url)
    return h


def test_php74_is_deprecated():
    r = eol.check("php", "7.4", "2026-07-14", http=_http({"php": _PHP}))
    assert r["status"] == "DEPRECATED" and r["eol_date"] == "2022-11-28" and r["cycle"] == "7.4"
    assert r["source_url"] == "https://endoflife.date/php"
    assert r["recommended"] == "8.3.10"          # newest supported cycle, not 7.4's dead latest


def test_php82_within_6_months_is_review():
    r = eol.check("php", "8.2", "2026-07-14", http=_http({"php": _PHP}))   # eol 2026-12-31
    assert r["status"] == "REVIEW"


def test_php83_far_future_is_ok():
    r = eol.check("php", "8.3", "2026-07-14", http=_http({"php": _PHP}))
    assert r["status"] == "OK"


def test_node_matches_major_from_full_version():
    r = eol.check("node", "15.14.0", "2026-07-14", http=_http({"nodejs": _NODE}))
    assert r["slug"] == "nodejs" and r["cycle"] == "15" and r["status"] == "DEPRECATED"


def test_untracked_product_returns_none():
    assert eol.check("react", "19.0.0", "2026-07-14", http=_http({})) is None
    assert eol.check("php", None, "2026-07-14", http=_http({"php": _PHP})) is None


_MAGENTO = [
    {"cycle": "2.4.7", "eol": "2027-05-31", "latest": "2.4.7-p3"},
    {"cycle": "2.4.6", "eol": "2026-08-11", "latest": "2.4.6-p8"},
    {"cycle": "2.4.4", "eol": "2025-04-12", "latest": "2.4.4-p13"},
]


def test_magento_package_maps_to_endoflife_slug():
    assert eol.product_slug("magento/product-community-edition") == "magento"
    assert eol.product_slug("magento/product-enterprise-edition") == "magento"


def test_magento_244_is_eol():
    # a Magento STORE repo (composer requires magento/product-community-edition 2.4.4) -> EOL
    r = eol.check("magento/product-community-edition", "2.4.4", "2026-07-31",
                  http=_http({"magento": _MAGENTO}))
    assert r["slug"] == "magento" and r["status"] == "DEPRECATED" and r["eol_date"] == "2025-04-12"
    assert r["source_url"] == "https://endoflife.date/magento"


def test_magento_is_classified_as_a_framework():
    from agent.lib.frameworks import is_framework
    assert is_framework("composer", "magento/product-community-edition")
    assert is_framework("composer", "magento/product-enterprise-edition")

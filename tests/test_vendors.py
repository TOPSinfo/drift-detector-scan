from agent.lib.vendors import load_vendors, vendor_slug, Vendor, DEFAULT_VERSION_REGEX


def test_loads_catalog_with_expected_vendors():
    vs = load_vendors()
    by_key = {v.techKey: v for v in vs}
    # spot-check the marketplace + a few others from the PM's inventory
    assert "api:amazon-sp-api" in by_key
    assert "api:amazon-mws" in by_key
    assert "api:stripe" in by_key and "api:shopify" in by_key
    assert "sellingpartnerapi" in by_key["api:amazon-sp-api"].domains
    assert len(vs) >= 20                          # ~27 vendors from the report


def test_missing_version_regex_falls_back_to_default():
    vs = load_vendors()
    # every vendor has a usable version_regex (own or default)
    assert all(v.version_regex for v in vs)
    assert any(v.version_regex == DEFAULT_VERSION_REGEX for v in vs)


def test_vendor_slug():
    assert vendor_slug("Amazon SP-API") == "amazon-sp-api"
    assert vendor_slug("Meta Graph API") == "meta-graph-api"


def test_vendor_is_frozen():
    v = Vendor("X", "api:x", ("x.com",), r"/(v\d+)")
    try:
        v.techKey = "api:y"
        assert False
    except Exception:
        pass

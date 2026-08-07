from agent.lib.classify_url import path_literal_of, version_of


def test_path_literal_of_extracts_versioned_path():
    assert path_literal_of("$resource_path = '/orders/2026-01-01/orders';") == "/orders/2026-01-01/orders"
    assert path_literal_of('$p = "/catalog/v0/items";') == "/catalog/v0/items"
    # no version segment -> not a candidate
    assert path_literal_of("$p = '/local/file/path';") == ""
    # a full URL is not a path literal (handled elsewhere)
    assert path_literal_of("$u = 'https://api.x.com/v1/foo';") == ""
    # version extraction on a bare path reuses version_of
    assert version_of("/orders/2026-01-01/orders", None) == "2026-01-01"
    assert version_of("/catalog/v0/items", None) == "v0"


def test_operation_of_reads_the_api_operation_name():
    from agent.lib.classify_url import operation_of
    # eBay Trading: the XML request root names the operation
    assert operation_of("$b = '<?xml version=\"1.0\"?><GetCategoryFeaturesRequest xmlns=\"urn:ebay\">'") \
        == "GetCategoryFeatures"
    assert operation_of('<AddDisputeRequest xmlns="urn:ebay:apis:eBLBaseComponents">') == "AddDispute"
    # the call-name argument form (becomes the X-EBAY-API-CALL-NAME header)
    assert operation_of('$session = $this->getEbaySession("GetCategories", $credentials);') == "GetCategories"
    assert operation_of("'X-EBAY-API-CALL-NAME: ' . $verb") == ""      # a variable is not a name
    # never guesses
    assert operation_of("$x = 'just a string';") == ""
    assert operation_of("<div>Request</div>") == ""                    # lowercase tag, not an operation


def test_path_literal_does_not_require_a_leading_slash():
    """Regression: requiring a leading '/' silently DROPPED literals written as
    "post-order/v2/cancellation" — the engine matched them, this returned "", and
    they appeared in neither attribution nor residue. Invisible, not merely
    unattributed, which is the one thing the coverage verdict must never allow.
    On one real file this under-reported residue 2 -> 41."""
    from agent.lib.classify_url import path_literal_of
    assert path_literal_of('$u = "post-order/v2/cancellation/";') == "post-order/v2/cancellation/"
    assert path_literal_of('$u = "/post-order/v2/return/";') == "/post-order/v2/return/"
    # still excludes what it should
    assert path_literal_of("$u = 'https://api.x.com/v1/foo';") == ""      # full URL
    assert path_literal_of("$u = '/local/file/path';") == ""              # no version segment
    assert path_literal_of("$u = 'v2';") == ""                            # not a path


def test_denoise_front_end_libs_and_static_asset_hosts():
    from agent.lib.classify_url import is_ignored
    # front-end libs / editors / icons / placeholders + vendor STATIC assets (not the API)
    for h in ("ckeditor.com", "docs.ckeditor.com", "popper.js.org", "feathericons.com",
              "jqueryui.com", "placehold.jp", "iso.org", "www.iso.org", "www.macromedia.com",
              "ir.ebaystatic.com"):
        assert is_ignored(h), h


def test_malformed_extraction_artifacts_are_ignored():
    from agent.lib.classify_url import is_ignored
    for h in ("...", "sandbox.", "ckeditor.com\\x3c", ".foo.com", "a..b.com"):
        assert is_ignored(h), h


def test_real_api_and_bucket_hosts_survive_the_denoise():
    from agent.lib.classify_url import is_ignored
    for h in ("api.ebay.com", "sellingpartnerapi-fe.amazon.com", "graph.microsoft.com",
              "velocityfrequentflyerau-prod.mirakl.net",
              "cw-prod-bucket-for-application-1234.s3.ap-southeast-2.amazonaws.com"):
        assert not is_ignored(h), h

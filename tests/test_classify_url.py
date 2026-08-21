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





def test_amazon_mws_matches_every_regional_tld():
    """MWS is deprecated; the regional endpoints (.co.uk/.de/…) must classify as Amazon MWS — not
    just .com — so the sunset flags everywhere it's still called."""
    from agent.lib.classify_url import classify_host
    from agent.lib.vendors import Vendor
    mws = Vendor("Amazon MWS", "api:amazon-mws", ("amazonservices",), r"/(v\d+)")
    for h in ("mws.amazonservices.co.uk", "mws.amazonservices.de", "mws.amazonservices.com"):
        v = classify_host(h, [mws])
        assert v and v.vendor == "Amazon MWS", h


# F4 (product-owner decision): RFC 2606 / RFC 6761 reserve these TLDs so they can never resolve
# to a real service, but dropping them via is_nonhost still made the host DISAPPEAR from the
# inventory. They must instead be VISIBLE (boilerplate, excluded from the audit backlog) — see
# agent/host_reputation.yaml's `test`/`example`/`invalid` entries and host_class.classify.
def test_reserved_tlds_survive_is_nonhost_and_classify_as_boilerplate():
    from agent.lib import host_class
    from agent.lib.classify_url import is_nonhost
    # NOT an "api."-labelled host here: that label independently wins over reputation
    # (test_api_label_beats_a_reputationed_parent_domain) and would classify api-lead instead —
    # still visible either way, but this test pins the boilerplate path specifically.
    for host in ("cdn.example.test", "backend.foo.invalid", "svc.example"):
        assert not is_nonhost(host), host
        assert host_class.classify(host) == "boilerplate", host


# The PRE-EXISTING placeholder entries (not RFC-reserved TLDs, just placeholder conventions)
# keep their original hard-dropped behaviour exactly as before F4.
def test_preexisting_placeholder_domains_are_still_hard_dropped():
    from agent.lib.classify_url import is_nonhost
    for host in ("thing.localhost", "shop.example.com", "api.test.com"):
        assert is_nonhost(host), host


def test_a_real_domain_that_merely_looks_like_a_placeholder_survives():
    """acme.com is a REAL registrable domain — it must stay visible and be typed by
    host_class (Task 1), never dropped here."""
    from agent.lib.classify_url import is_nonhost
    assert not is_nonhost("acme.com")
    assert not is_nonhost("testing-services.io")
    assert not is_nonhost("api.exampletree.com")


# ── XML namespaces are identifiers, not endpoints ────────────────────────────────
# Measured across a 19-repo corpus: 492 of 4273 attributed call-sites (11.5%) are namespace
# URIs. For Amazon MWS that was 114 of 151 — three quarters of the vendor's "call-sites".
# A namespace URI names a vocabulary; nothing ever fetches it.
#
# `_IGNORE` cannot express this: it filters by HOST, and the namespace host IS the vendor's
# own API host, so ignoring it would delete that vendor's real call-sites too.
#
# BOTH forms are required. An earlier attempt handled only the xmlns= attribute and removed
# nothing measurable, because these SDKs declare the same namespace both ways in the same
# file — filtering one left the loc attributed by the other.

def test_xml_namespace_attribute_is_not_extracted():
    from agent.lib.classify_url import extract_urls
    assert extract_urls(
        '$r = \'<GetOrderResponse xmlns="http://mws.amazonservices.com/schema/2011-10-01">\';') == []


def test_escaped_quote_namespace_is_also_excluded():
    """The SDKs build these inside double-quoted PHP strings, so the quotes arrive
    backslash-escaped. Matching only bare quotes missed every real occurrence."""
    from agent.lib.classify_url import extract_urls
    assert extract_urls(
        '$xml .= "<GetCompetitivePricingForASINResponse xmlns=\\"http://mws.amazonservices.com/schema/Products/2011-10-01\\">";') == []


def test_prefixed_namespace_is_excluded():
    from agent.lib.classify_url import extract_urls
    assert extract_urls(
        '$q = \'<abortJobRequest xmlns:sct="http://www.ebay.com/soaframework/common/types">\';') == []


def test_registered_namespace_call_is_excluded():
    """The second form, and the reason the first attempt failed. This exact line appears 30
    times in the corpus, in the same files as the xmlns= form."""
    from agent.lib.classify_url import extract_urls
    assert extract_urls(
        "$xpath->registerNamespace('a', 'http://mws.amazonaws.com/doc/2009-01-01/');") == []


def test_a_real_url_on_a_line_that_also_has_a_namespace_survives():
    """Per-URL, not per-line. A SOAP client routinely declares the namespace and posts to the
    endpoint on the SAME line; dropping the line would lose the actual call."""
    from agent.lib.classify_url import extract_urls
    assert extract_urls(
        '$c->post("https://mws.amazonservices.com/Orders/2013-09-01", '
        '\'<GetOrder xmlns="http://mws.amazonservices.com/schema/2011-10-01"/>\');'
    ) == ["https://mws.amazonservices.com/Orders/2013-09-01"]


def test_ordinary_urls_are_untouched():
    from agent.lib.classify_url import extract_urls
    assert extract_urls('$u = "https://api.stripe.com/v1/charges";') == \
        ["https://api.stripe.com/v1/charges"]


def test_the_dead_ignore_taxonomy_stays_deleted():
    """`is_ignored` and its `_IGNORE` set were a SECOND host taxonomy that nothing called. They
    are gone as of v1.0.0; this test keeps them gone.

    Why it is worth a test rather than a comment: the dead code cost a wrong fix once. Four
    documentation hosts were added to `_IGNORE` to clear them from the fleet's resolution
    queue; the unit test passed because it called `is_ignored` DIRECTLY, and the hosts kept
    appearing on the next fleet run because no production code path reached the function.

    Host triage belongs in ONE place — `host_reputation.yaml` via `host_class` — plus
    `is_nonhost` for extraction artefacts. If someone reintroduces a second filter here, this
    fails and they have to decide deliberately which one actually decides."""
    import pathlib as _p
    src = (_p.Path(__file__).resolve().parent.parent / "agent" / "lib" / "classify_url.py").read_text()
    assert "def is_ignored" not in src, "the dead second host taxonomy is back — see host_reputation.yaml"
    assert "_IGNORE = {" not in src


def test_the_vendors_real_api_hosts_are_still_classified():
    """The boundary: ignoring an AWS *docs* domain must not touch the AWS API domain, and
    ignoring GitHub's raw host must not silently drop a genuine api.github.com integration."""
    from agent.lib.classify_url import is_nonhost
    from agent.lib import host_class
    for h in ("s3.amazonaws.com", "sqs.us-east-1.amazonaws.com", "api.github.com"):
        assert not is_nonhost(h), h                       # not an extraction artefact
        assert host_class.classify(h) != "boilerplate", h  # and not filed as a doc/link host

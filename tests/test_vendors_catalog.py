from agent.lib import classify_url, vendors as vendors_mod


def _vendors():
    return vendors_mod.load_vendors()


# Found by the AI cross-check plane and confirmed in code on a real repo: the scanner SAW these
# hosts but could not classify them, so they sat in `queued` and never reached the catalog layer.
# Detection is the gap here, not the retirement catalog.
def test_the_three_confirmed_integrations_classify():
    v = _vendors()
    assert classify_url.classify_host("api.justcall.io", v).vendor == "JustCall"
    assert classify_url.classify_host("hooks.zapier.com", v).vendor == "Zapier"
    assert classify_url.classify_host("login.microsoftonline.com", v).vendor == "Microsoft Identity"


# M3: Zapier was narrowed to its webhook-trigger host (hooks.zapier.com, see F6 above), but
# api.zapier.com is a second, real, resolving Zapier API host — narrowed the same way, not a
# revert to the bare zapier.com marketing domain.
def test_zapier_api_host_classifies_alongside_the_webhook_host():
    v = _vendors()
    assert classify_url.classify_host("api.zapier.com", v).vendor == "Zapier"
    assert classify_url.classify_host("hooks.zapier.com", v).vendor == "Zapier"


# A dependency's published config enumerates these. Whether a code path selects them is a separate
# question from whether the code references them — classify them, then let the attestation layer
# say (honestly) that nobody has checked their retirement lists.
def test_the_ai_provider_hosts_classify():
    v = _vendors()
    for host, vendor in [("api.deepseek.com", "DeepSeek"), ("api.groq.com", "Groq"),
                         ("api.mistral.ai", "Mistral AI"), ("api.x.ai", "xAI"),
                         ("openrouter.ai", "OpenRouter"), ("api.elevenlabs.io", "ElevenLabs"),
                         ("api.voyageai.com", "Voyage AI")]:
        got = classify_url.classify_host(host, v)
        assert got is not None and got.vendor == vendor, host


# F6 (product-owner decision): the catalog entry is the vendor's SPECIFIC API host, not its bare
# marketing domain — a README link to https://justcall.io (the homepage) must not count as a
# tracked integration. Narrowed from the bare domains this branch originally shipped.
def test_bare_marketing_domains_no_longer_classify():
    v = _vendors()
    for host in ("justcall.io", "zapier.com", "deepseek.com", "groq.com", "mistral.ai", "x.ai",
                 "elevenlabs.io", "voyageai.com"):
        assert classify_url.classify_host(host, v) is None, host


def test_new_vendors_are_unaudited_not_silently_current():
    """Classifying a vendor must NOT imply its retirements are checked. These nine have no
    attestation, so the catalog verdict stays UNAUDITED — 0 findings for them is not 'clean'.

    Microsoft Identity was in this list until 2026-08-20, when its breaking-changes page was
    actually read and it was attested. It moved to the test below rather than being dropped:
    a vendor leaving this list must be provably audited, not merely un-asserted.

    Anchored against the empty-catalog false-pass: verdict_for() on a name absent from `v` (a
    typo, a renamed vendor) ALSO reads UNAUDITED, so the loop below additionally asserts each
    vendor's specific host still classifies — proving the vendor is actually IN the catalog, not
    merely that its name string happens to also be absent from attestations."""
    from agent.lib import catalog_coverage
    v = _vendors()
    att = catalog_coverage.load_attestations()
    hosts = {"JustCall": "api.justcall.io", "Zapier": "hooks.zapier.com",
             "DeepSeek": "api.deepseek.com",
             "Groq": "api.groq.com", "Mistral AI": "api.mistral.ai", "xAI": "api.x.ai",
             "OpenRouter": "openrouter.ai", "ElevenLabs": "api.elevenlabs.io",
             "Voyage AI": "api.voyageai.com"}
    for vendor, host in hosts.items():
        got = classify_url.classify_host(host, v)
        assert got is not None and got.vendor == vendor, vendor
        assert catalog_coverage.verdict_for(vendor, att, "2026-08-12")[0] == "UNAUDITED"


def test_microsoft_identity_is_audited_with_a_fetched_source():
    """The other half of the test above: this vendor left the unaudited list because its
    canonical breaking-changes page was read in full, not because the assertion was dropped."""
    from agent.lib import catalog_coverage
    att = catalog_coverage.load_attestations()
    assert catalog_coverage.verdict_for("Microsoft Identity", att, "2026-08-20")[0] == "CURRENT"
    rec = att["Microsoft Identity"]          # load_attestations() is keyed BY vendor
    assert "learn.microsoft.com" in rec["source"]
    assert rec["by"] == "ai-research"        # weaker than a human's, and shown as such


def test_usps_is_scoped_to_the_two_real_api_hosts():
    """USPS's API traffic goes to secure.shippingapis.com (Web Tools, retired 2026-01-25)
    and apis.usps.com (the replacement REST platform).

    `tools.usps.com` is NOT an API host — every reference to it on USPS's own pages is a
    consumer link (/tracking/, /locations/, /zip-code-lookup.htm, /schedule-pickup-steps.htm).
    An earlier version of this entry used it, which counted tracking URLs pasted into mail
    templates as a USPS API integration while the host that is actually retiring classified
    as nothing at all. `www.usps.com` is the retail storefront — same failure."""
    from agent.lib import vendors as vendors_mod
    from agent.lib import classify_url
    # Package catalog only — load_vendors() with no path also layers ~/.drift/catalog,
    # and a local resolve overlay can reintroduce tools.usps.com as USPS. This test pins
    # agent/vendors.yaml.
    v = vendors_mod.load_vendors(path=vendors_mod._DEFAULT_VENDORS)
    for host in ("secure.shippingapis.com", "apis.usps.com"):
        hit = classify_url.classify_host(host, v)
        assert hit is not None and hit.vendor == "USPS", (host, hit)
    for host in ("tools.usps.com", "www.usps.com"):
        miss = classify_url.classify_host(host, v)
        assert miss is None or miss.vendor != "USPS", (host, miss)


# ── eBay Post-Order: a pathSignature, because the host is never on the line ──────────
# Measured on a 19-repo corpus: 50 versioned `post-order/vN/` literals across 3 repos, every
# one inside a file named Ebay_post_order_api.php under an ebay/ directory, zero
# counter-examples. The wrapper stores bare paths and builds the host elsewhere, so neither
# host classification nor the single-vendor concat idiom can reach them.

def test_ebay_declares_a_post_order_path_signature():
    v = _vendors()
    ebay = next(x for x in v if x.vendor == "eBay")
    assert ebay.path_signature, "eBay must declare a pathSignature for the Post-Order API"
    got = classify_url.path_signature_match("post-order/v2/cancellation/12345", v)
    assert got and got[0].vendor == "eBay"
    assert got[1] == "v2", "group 1 of the signature is the version"


def test_the_post_order_signature_does_not_match_a_lookalike_segment():
    """The literals in the wild carry NO leading slash ('post-order/v2/cancellation'), so the
    signature cannot require one — which is exactly what would let it match the tail of an
    unrelated segment. A boundary is required instead, or an app's own /my-post-order/v2/
    route would be tagged as eBay."""
    v = _vendors()
    assert classify_url.path_signature_match("my-post-order/v2/thing", v) is None
    assert classify_url.path_signature_match("/post-order/v2/thing", v) is not None
    assert classify_url.path_signature_match("post-order/v2/thing", v) is not None


def test_the_post_order_signature_does_not_steal_shopify_paths():
    """Two signatures now exist; longest-match-wins must keep them apart."""
    v = _vendors()
    got = classify_url.path_signature_match("/admin/api/2023-10/shop.json", v)
    assert got and got[0].vendor == "Shopify" and got[1] == "2023-10"


# ── Salesforce Commerce Cloud: a per-CUSTOMER host, so only the path identifies it ──
# Found on the fleet's resolution queue as a merchant-owned host — which reads like a
# customer's own domain, and in a sense is: OCAPI is served from each merchant's own
# Commerce Cloud host. A domains: entry can therefore never work, exactly like Magento.
#
# The PATH is unmistakable. Salesforce documents it as
# `example.com/dw/shop/v24_5/products/foo`, so `/dw/{shop|data|meta}/v{version}/` identifies
# OCAPI on anyone's host — the same argument as Shopify's /admin/api/{version}/.

def test_salesforce_commerce_cloud_is_identified_by_its_ocapi_path():
    v = _vendors()
    sfcc = next(x for x in v if x.vendor == "Salesforce Commerce Cloud")
    assert sfcc.domains == (), "OCAPI is served per-merchant; a host list cannot identify it"
    got = classify_url.path_signature_match(
        "https://shop.example-merchant.com/s/AU/dw/shop/v24_5/products", v)
    assert got and got[0].vendor == "Salesforce Commerce Cloud"
    assert got[1] == "v24_5", "group 1 is the OCAPI version, which is what goes obsolete"


def test_the_ocapi_signature_covers_the_other_api_types():
    """`shop`, `data` and `meta` are the three OCAPI types in Salesforce's URL syntax."""
    v = _vendors()
    for kind in ("shop", "data", "meta"):
        got = classify_url.path_signature_match(f"https://m.example.com/dw/{kind}/v23_2/x", v)
        assert got and got[0].vendor == "Salesforce Commerce Cloud", kind


def test_the_ocapi_signature_matches_a_base_url_with_no_trailing_slash():
    """THE REAL CASE, and the one the first version of this signature missed: the fleet
    stores it as a base_url — `https://<merchant-host>/s/AU/dw/shop/v24_5`
    — with nothing after the version. Requiring a trailing slash matched the documentation
    example and none of the actual code."""
    v = _vendors()
    got = classify_url.path_signature_match(
        "'base_url' => 'https://shop.example-merchant.com/s/AU/dw/shop/v24_5'", v)
    assert got and got[0].vendor == "Salesforce Commerce Cloud"
    assert got[1] == "v24_5"


def test_the_ocapi_signature_does_not_match_an_unrelated_dw_path():
    """`/dw/` alone is not enough — it must be OCAPI-shaped, or a merchant's /dw/ download
    directory would be claimed as an integration."""
    v = _vendors()
    assert classify_url.path_signature_match("https://x.example.com/dw/assets/logo.png", v) is None

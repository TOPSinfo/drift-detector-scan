"""Deterministic host triage (`hostClass`) — the M1 classifier.

Guards the taxonomy that turns the "wall of unknowns" into a ranked list: real API leads on
top, noise bucketed but never hidden. `hostClass` is orthogonal to vendor classification —
nothing here may set `classified`/`vendor`/a date.
"""
import pytest
from agent.lib import host_class as hc
from agent.lib import own_infra


def test_reputation_beats_heuristics():
    assert hc.classify("connect.facebook.net") == "analytics"      # tracker list
    assert hc.classify("fonts.googleapis.com") == "asset-cdn"      # from old _IGNORE
    assert hc.classify("static.hotjar.com") == "analytics"


def test_social_share_grammar():
    assert hc.classify("wa.me", url="https://wa.me/15551234") == "social-widget"
    assert hc.classify("x.com", url="https://x.com/intent/tweet?text=x") == "social-widget"
    assert hc.classify("pinterest.com", url="https://pinterest.com/pin/create/button/") == "social-widget"


def test_share_grammar_works_on_hosts_absent_from_the_catalog():
    """The grammar is host-INDEPENDENT — that is its whole point. A share URL on a host the
    reputation catalog has never seen must still be recognized as a button, not an API call.
    (Without this, the catalog would have to enumerate every site with a share widget.)"""
    assert hc.classify("blog.example.org", url="https://blog.example.org/sharer/post?id=2") == "social-widget"


def test_api_shape_in_call_context_is_a_lead():
    # api. label / versioned path / inside an HTTP-client call -> a real lead, not noise
    assert hc.classify("api.greatschools.org", url="https://api.greatschools.org/v2/schools",
                       in_call=True) == "api-lead"


def test_api_labeled_host_is_a_lead_without_a_versioned_path_or_call():
    """A real repo (acmegrocer-foods) reaches api.keepa.com / api.printnode.com / geocode-api.arcgis.com
    with no /vN path and via wrappers we don't sniff as calls. The `api.`/`api-`/`-api.` label alone
    is a strong enough API signal to surface them as leads, not bury them in 'pending audit'."""
    for host in ("api.keepa.com", "api.printnode.com", "api.sellersnap.io",
                 "geocode-api.arcgis.com", "api.bluecartapi.com"):
        assert hc.classify(host) == "api-lead", host


def test_asset_by_extension_or_path():
    assert hc.classify("images.unsplash.com", url="https://images.unsplash.com/photo-1.jpg") == "asset-cdn"
    assert hc.classify("cdn.example.com", file_ext=".css") == "asset-cdn"


def test_unknown_with_no_signal_is_unclassified_not_hidden():
    assert hc.classify("api-gateway.internal.acme.io") in ("api-lead", "unclassified")
    # NOT "weird-host.example" — since F4, `.example` is a reserved-TLD entry in
    # host_reputation.yaml's `boilerplate` list (see test_reserved_tld_hosts_classify_boilerplate
    # below), so a host under it is no longer the "nothing matches" case this test wants.
    assert hc.classify("weird-host.zzqux-nonexistent-tld") == "unclassified"


def test_reserved_tld_hosts_classify_boilerplate():
    """F4 (product-owner decision): RFC 2606/6761 reserved TLDs (.test/.example/.invalid) are no
    longer hard-dropped by classify_url — they reach here and must classify `boilerplate`
    (visible, excluded from the audit backlog), never `unclassified` (which would misread as an
    unaudited lead) and never silently disappear."""
    for host in ("cdn.example.test", "svc.example", "thing.foo.invalid"):
        assert hc.classify(host) == "boilerplate", host


def test_reputation_matches_on_registrable_suffix():
    """Mirrors classify_url's suffix rule: a subdomain inherits its parent's bucket, so the
    catalog stays small (`jsdelivr.net` covers `cdn.jsdelivr.net`)."""
    assert hc.classify("cdn.jsdelivr.net") == "asset-cdn"
    assert hc.classify("www.w3.org") == "boilerplate"


def test_analytics_vendors_with_real_apis_are_not_pre_buried():
    """The reason M1 refuses an imported tracker blocklist (see the plan's "Decision: no
    imported blocklist"). segment.com/mixpanel.com/intercom.io sit on every public tracker
    list, yet each ships a VERSIONED API that gets deprecated. Bucketing them `analytics`
    would collapse them into the noise panel — the honesty principle inverted by the very
    feature meant to strengthen it. They must stay attention-worthy here; if they are ever
    tracked, they belong in vendors.yaml (which sets hostClass `api` upstream instead).

    This test FAILS the moment someone bulk-imports a blocklist into host_reputation.yaml.
    """
    for host in ("segment.com", "api.segment.io", "mixpanel.com", "intercom.io",
                 "amplitude.com"):
        assert hc.classify(host) != "analytics", f"{host} pre-buried as analytics"


def test_api_label_beats_a_reputationed_parent_domain():
    """business-api.tiktok.com is the TikTok API, not a social widget, and api.cloudflare.com is a
    lead, not a CDN — an api. label wins over the parent domain's reputation. A host with NO api
    label (www.tiktok.com) still follows reputation."""
    assert hc.classify("business-api.tiktok.com") == "api-lead"
    assert hc.classify("api.cloudflare.com") == "api-lead"
    assert hc.classify("www.tiktok.com") == "social-widget"


def test_own_cloud_backends_are_own_infra():
    """Account-specific cloud endpoints are the deployer's OWN infra, never a third-party you
    integrate WITH — so they must not sit in 'pending audit' as if they were a vendor."""
    assert hc.classify("tpncy-web-services.auth.us-east-1.amazoncognito.com") == "own-infra"
    assert hc.classify("myapp.herokuapp.com") == "own-infra"
    assert hc.classify("svc-x.cloudfunctions.net") == "own-infra"
    assert hc.classify("myserver.mooo.com") == "own-infra"    # dynamic-DNS = self-hosted, not a vendor
    assert not hc.is_integration("own-infra")


def test_every_result_is_in_the_closed_vocabulary():
    """The vocab is a closed set shared by endpoints.py (write), dashboard_render.py
    (project+count), verify.py (check) and the cockpit (group). No name drift."""
    assert hc.VOCAB == {"api", "api-lead", "social-widget", "asset-cdn", "analytics",
                        "vendored-lib", "boilerplate", "own-infra", "unclassified"}
    samples = [
        ("fonts.gstatic.com", {}), ("wa.me", {"url": "https://wa.me/1"}),
        ("api.stripe.com", {"url": "https://api.stripe.com/v1/charges", "in_call": True}),
        ("weird.example", {}), ("cdn.x.io", {"file_ext": ".scss"}),
        ("", {}), ("jquery.com", {}),
    ]
    for host, kw in samples:
        assert hc.classify(host, **kw) in hc.VOCAB


def test_classification_is_deterministic():
    """Principle 3: same inputs -> same output, every call. No wall-clock, no ordering luck."""
    args = ("api.greatschools.org",)
    kw = {"url": "https://api.greatschools.org/v2/schools", "in_call": True}
    assert len({hc.classify(*args, **kw) for _ in range(25)}) == 1


def test_empty_or_junk_host_is_unclassified_never_crashes():
    """Junk reaches the classifier from URL-extraction artifacts; it must bucket, not raise.
    (The genuine non-hosts — localhost, example.com, raw IPs — are hard-dropped upstream in
    classify_url.is_nonhost; that stays Task 3's job, not this classifier's.)"""
    for junk in ("", None, "...", "sandbox."):
        assert hc.classify(junk) == "unclassified"


# Each host below sat in `queued` on a real Laravel scan, described as "an API service we haven't
# researched yet". None of them is an API service. rfc-editor.org is the tell: the same host was
# ALREADY excluded as boilerplate through another path, so the queue and the exclusion list
# disagreed with each other about the same domain.
@pytest.mark.parametrize("host,expected", [
    ("spdx.org", "boilerplate"),
    ("spec.openapis.org", "boilerplate"),
    ("www.rfc-editor.org", "boilerplate"),
    ("reactjs.org", "boilerplate"),
    ("redux.js.org", "boilerplate"),
    ("vladimirgorej.com", "boilerplate"),
    ("acme.com", "boilerplate"),
    ("fb.me", "social-widget"),
    ("www.snapchat.com", "social-widget"),
    ("www.threads.net", "social-widget"),
    ("soundcloud.com", "social-widget"),
    ("get.adobe.com", "asset-cdn"),
])
def test_queue_noise_is_bucketed_not_queued(host, expected):
    assert hc.classify(host) == expected


# The same failure, measured again on the live fleet scan of 2026-09-01: 222 endpoints across 167
# hosts sat in `queued`, and the work-order issue asked a human to name all of them. The single
# largest entry was an image CDN with 186 call sites. Each host below was confirmed at its
# file:line before being classified here — none is a service anyone calls:
#
#   ssl-images-amazon.com  product image URLs built from Keepa image tokens
#   ebayimg.com            eBay listing image URLs in the product-posting path
#   flagpedia.net          flag images inside a vis-timeline documentation template
#   phpexcel.net           the vendored PHPExcel library's own site, linked from its HTML writer
#   openoffice.org         ODF XML namespace declarations in PHPExcel's OpenDocument writer
#
# Only GENERIC hosts belong here. The rest of that queue is client- and vendor-specific (supplier
# image hosts, B2B portals), and those are catalogued in the private drift-ops overlay — putting
# them in this public tree is the leak `tests/test_no_internal_identifiers.py` exists to refuse.
@pytest.mark.parametrize("host,expected", [
    ("images-na.ssl-images-amazon.com", "asset-cdn"),
    ("ssl-images-amazon.com", "asset-cdn"),
    ("i.ebayimg.com", "asset-cdn"),
    ("flagpedia.net", "asset-cdn"),
    ("www.phpexcel.net", "vendored-lib"),
    ("openoffice.org", "boilerplate"),
    ("www.openoffice.org", "boilerplate"),
])
def test_fleet_queue_noise_2026_09_01_is_bucketed(host, expected):
    assert hc.classify(host) == expected


# A registrable-domain suffix entry must not swallow a sibling that IS a real API. amazon.com's
# APIs live on other registrable domains entirely, but assert it so a future broadening of the
# image-CDN entry cannot silently hide one.
@pytest.mark.parametrize("host", [
    "sellingpartnerapi-na.amazon.com",
    "api.ebay.com",
])
def test_image_cdn_entries_do_not_swallow_real_vendor_apis(host):
    assert hc.classify(host) != "asset-cdn"


@pytest.mark.parametrize("host", [
    "spdx.org", "www.rfc-editor.org", "fb.me", "soundcloud.com", "get.adobe.com", "acme.com",
])
def test_bucketed_hosts_are_not_integrations(host):
    """`is_integration` False is what keeps them out of the audit backlog — the queue count."""
    assert not hc.is_integration(hc.classify(host))


def _sig():
    return own_infra.signals(repo_path="/srv/zenithapp-crm",
                             repo_id="https://git.devhost.io/root/zenithapp-crm.git")


def test_own_infra_wins_over_the_api_label_rule():
    """Ordering matters and is the whole point: `api.<client>.com` is the client's OWN API, not a
    third-party lead. The `api.` label rule runs early, so own-infra must run before it."""
    assert hc.classify("api.zenithapp.io", own=_sig()) == "own-infra"
    assert hc.classify("crm.zenithapp.io", own=_sig()) == "own-infra"
    assert hc.classify("qa-zenithapp-idx.devhost.io", own=_sig()) == "own-infra"


def test_own_infra_never_claims_a_third_party():
    for host in ("api.justcall.io", "hooks.zapier.com", "graph.microsoft.com"):
        assert hc.classify(host, own=_sig()) != "own-infra", host


def test_classify_without_signals_is_unchanged():
    """The `own` keyword is optional; every existing caller must behave identically without it."""
    assert hc.classify("crm.zenithapp.io") == "unclassified"
    assert hc.classify("api.justcall.io") == "api-lead"


def test_documentation_hosts_classify_as_boilerplate_not_a_lead():
    """Found on the fleet's resolution queue: curl's manual, Guzzle's docs and GitHub's raw
    file host sat there as "unresolved integrations" nobody could ever resolve.

    This is the SECOND attempt at this. The first added them to classify_url._IGNORE — which
    is dead code: `is_ignored` has no callers anywhere in the tool, so the entry changed
    nothing and the hosts kept appearing. The unit test passed because it called is_ignored
    directly. host_class is what actually runs, and `boilerplate` is its existing bucket for
    exactly this ("links & namespaces, never a runtime integration")."""
    from agent.lib import host_class
    for host in ("curl.haxx.se", "docs.guzzlephp.org", "raw.githubusercontent.com"):
        assert host_class.classify(host) == "boilerplate", host


def test_a_real_api_host_is_untouched_by_those_entries():
    """githubusercontent.com must not drag api.github.com with it, and the AWS docs domain
    must not touch the AWS API domain."""
    from agent.lib import host_class
    assert host_class.classify("api.github.com") == "api-lead"
    assert host_class.classify("s3.amazonaws.com") != "boilerplate"

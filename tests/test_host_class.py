"""Deterministic host triage (`hostClass`) — the M1 classifier.

Guards the taxonomy that turns the "wall of unknowns" into a ranked list: real API leads on
top, noise bucketed but never hidden. `hostClass` is orthogonal to vendor classification —
nothing here may set `classified`/`vendor`/a date.
"""
from agent.lib import host_class as hc


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
    """A real repo (sebago-foods) reaches api.keepa.com / api.printnode.com / geocode-api.arcgis.com
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
    assert hc.classify("weird-host.example") == "unclassified"


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

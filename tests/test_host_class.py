"""host_class triages UNCATALOGUED hosts into a shown-integration vs excluded-non-integration class.

The bug this guards (the demo failure): a real project's egress list — greatschools, zillow, pexels,
whatsapp, hotjar — was labelled "unclassified/unknown", so *found* integrations read as *undetected*
and a viewer concluded the tool doesn't work. The fix SHOWS every found integration (breadth is the
value) and excludes only genuine non-integrations (bundled libs, asset CDNs, schemas).
"""
from agent.lib import host_class as hc


def test_reputation_classes_known_trackers_assets_libs_schemas():
    assert hc.classify("connect.facebook.net") == "analytics"
    assert hc.classify("static.hotjar.com") == "analytics"
    assert hc.classify("fonts.googleapis.com") == "asset-cdn"
    assert hc.classify("images.unsplash.com") == "asset-cdn"
    assert hc.classify("momentjs.com") == "library"       # a bundled date library, not a service
    assert hc.classify("keenthemes.com") == "library"     # the Metronic UI kit
    assert hc.classify("www.sitemaps.org") == "reference"  # a schema namespace


def test_social_and_analytics_are_SHOWN_as_integrations_not_hidden():
    assert hc.classify("wa.me", url="https://wa.me/15551234") == "social"
    assert hc.classify("whatsapp.com") == "social"
    assert hc.classify("tiktok.com") == "social"
    assert hc.classify("x.com", url="https://x.com/intent/tweet?text=hi") == "social"
    # breadth: analytics + social are third-party integrations, surfaced — not "noise"
    assert hc.is_integration("social")
    assert hc.is_integration("analytics")


def test_api_shaped_hosts_are_leads():
    assert hc.classify("api.greatschools.org", url="https://api.greatschools.org/v2/schools",
                       in_call=True) == "api-lead"
    assert hc.classify("api.pexels.com", url="https://api.pexels.com/v1/search",
                       in_call=True) == "api-lead"


def test_unknown_service_is_shown_pending_audit_not_excluded():
    # zillow: no api. label, but still a third-party service the app calls — err toward SHOWING it
    assert hc.classify("www.zillow.com") == "unclassified"
    assert hc.is_integration("unclassified")   # shown as "found · not yet audited"


def test_non_integrations_are_excluded_from_the_integration_count():
    for c in ("asset-cdn", "library", "reference"):
        assert not hc.is_integration(c)
    # every returned class is in the closed vocabulary
    assert set(hc.INTEGRATION_CLASSES) | set(hc.NON_INTEGRATION_CLASSES) == set(hc.ALL_CLASSES)

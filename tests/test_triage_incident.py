"""The geo-mapper incident, as a regression (principle 5: prove a guard against its bug).

A real-estate SPA scanned as a built copy produced a WALL of ~20 "unclassified" egress hosts. A
viewer read *found* integrations as *undetected* and concluded the tool doesn't work. This fixture
reproduces that repo in miniature — one real API call buried under social buttons, a stock-image
CDN, a bundled library, and a schema link — and asserts M1 turns the wall into a TYPED triage:

  • the ONE real API lead (api.greatschools.org) surfaces on top,
  • every found integration is SHOWN (zillow pending-audit, the social buttons typed), and
  • the bundled assets / libraries / schemas are EXCLUDED from the integration total.

Pre-M1 (no hostClass) every host was a flat "Unknown" with no `hostClass` field, so `e["hostClass"]`
raises KeyError and the leads list is empty — this test fails on the old behavior, which is the proof.
"""
import os
from collections import Counter

from agent.lib import classify_url, host_class
from agent.lib.endpoints import build_endpoints
from agent.lib.vendors import Vendor

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mls_incident")
# The scanned repo's own catalog does NOT know these vendors — that is the point (uncatalogued
# third parties must still be found + triaged, never dropped).
_VENDORS = [Vendor("Stripe", "api:stripe", ("stripe.com",), r'/(v\d+)')]


def _scan_fixture(fixture_dir):
    """Run the real discover-then-classify pipeline over the committed fixture (no engine needed:
    feed one url-match per line that holds a URL, exactly what ast-grep's url-literal rule emits)."""
    matches = []
    for root, _dirs, files in os.walk(fixture_dir):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), fixture_dir)
            with open(os.path.join(root, fn), encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    if classify_url.extract_urls(line):
                        matches.append({"kind": "url", "path": rel, "line": i})
    return build_endpoints(matches, fixture_dir, _VENDORS)


def test_incident_wall_of_unknowns_becomes_a_typed_triage():
    eps = _scan_fixture(FIXTURE)
    by_class = Counter(e["hostClass"] for e in eps)
    domains = {e["domain"] for e in eps}

    # the ONE real API lead surfaces, distinct from the noise
    leads = sorted(e["domain"] for e in eps if e["hostClass"] == "api-lead")
    assert leads == ["api.greatschools.org"]

    # a real service with no api-shape is still SHOWN (found · pending audit), not dropped
    assert "www.zillow.com" in {e["domain"] for e in eps if e["hostClass"] == "unclassified"}

    # the social buttons are typed + shown (breadth), not a scary "unknown" pile
    assert by_class["social-widget"] >= 4          # wa.me, tiktok, pinterest, x

    # the bundled assets / libraries / schema are EXCLUDED from the integration total
    excluded = {e["domain"] for e in eps if not host_class.is_integration(e["hostClass"])}
    assert {"fonts.googleapis.com", "images.unsplash.com", "momentjs.com",
            "cdn.keenthemes.com", "www.sitemaps.org"} <= excluded

    # the headline the demo needed: found integrations >= its one real lead, and the noise is OUT
    integrations = {e["domain"] for e in eps if host_class.is_integration(e["hostClass"])}
    assert "api.greatschools.org" in integrations and "www.zillow.com" in integrations
    assert not (excluded & integrations)           # partition: nothing is both
    assert domains == excluded | integrations

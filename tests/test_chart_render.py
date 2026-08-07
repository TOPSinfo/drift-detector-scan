"""chart.html — the ONLINE chart view. It embeds the SAME verifiable payload blob as the
dashboard (so verify proves the charts draw from drift.json), loads Chart.js from a CDN,
and degrades to a pointer at dashboard.html offline. Pure string/JSON assertions."""
import json
import re

from agent.lib.chart_render import render_chart
from agent.lib.verify import check_blob_matches_payload, Violation
import pytest


def _payload(**over):
    base = {
        "schemaVersion": "drift/v1", "generated": "2026-07-21",
        "counts": {"fixes": 3, "sunsets": 4, "pastDue": 2, "eol": 1, "critical": 0,
                   "unaudited": 0, "reposAffected": 2, "reposScanned": 3},
        "actions": [
            {"kind": "sunset", "ref": "eBay", "unit": "GetCategories", "status": "DEPRECATED",
             "date": "2025-01-01"},
            {"kind": "sunset", "ref": "eBay", "unit": "GetItem", "status": "REVIEW",
             "date": "2027-01-01"},
            {"kind": "sunset", "ref": "Amazon SP-API", "unit": "/fba/v0", "status": "DEPRECATED",
             "date": "2024-06-30"},
            {"kind": "sunset", "ref": "Amazon SP-API", "unit": "/orders/v0", "status": "REVIEW",
             "date": "2028-03-27"},
            {"kind": "cve", "ref": "npm/axios", "unit": None, "status": "DEPRECATED",
             "date": None},
        ],
    }
    base.update(over)
    return base


def _blob(html):
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    assert m, "drift-data blob not found"
    return json.loads(m.group(1).replace("\\u003c", "<"))


def test_is_an_html_document_with_the_three_charts():
    html = render_chart(_payload(), "2026-07-21")
    assert html.startswith("<!doctype html>")
    for canvas in ('id="risk"', 'id="byVendor"', 'id="schedule"'):
        assert canvas in html


def test_embeds_the_same_verifiable_payload_blob():
    payload = _payload()
    html = render_chart(payload, "2026-07-21")
    assert _blob(html) == payload
    # the dashboard's own parity check accepts it (same #drift-data contract)
    check_blob_matches_payload(html, json.dumps(payload), "chart.html")


def test_blob_parity_catches_a_tampered_chart():
    # the blob is compact (sort_keys, no spaces); tamper it and the parity check must fire
    payload = _payload()
    html = render_chart(payload, "2026-07-21")
    tampered = html.replace('"pastDue": 2', '"pastDue": 99')
    assert tampered != html, "the tamper anchor must have matched the compact blob"
    with pytest.raises(Violation):
        check_blob_matches_payload(tampered, json.dumps(payload), "chart.html")


def test_loads_chart_js_from_a_cdn_and_degrades_offline():
    html = render_chart(_payload(), "2026-07-21")
    assert "cdn.jsdelivr.net/npm/chart.js@" in html          # pinned CDN library
    assert 'onerror=' in html                                 # CDN-failure hook
    assert 'id="offline"' in html                             # the fallback message
    assert 'dashboard.html' in html                           # points at the offline artifact
    assert 'typeof Chart === "undefined"' in html             # guards a blocked CDN


def test_now_is_available_to_the_client_for_the_schedule_axis():
    html = render_chart(_payload(), "2026-07-21")
    assert 'data-now="2026-07-21"' in html


def test_deterministic():
    assert render_chart(_payload(), "2026-07-21") == render_chart(_payload(), "2026-07-21")


def test_scan_strings_are_escaped_in_the_chrome():
    # a hostile vendor ref must not break out of the embedded blob or the headline
    evil = 'x</script><img src=x onerror=alert(1)>'
    html = render_chart(_payload(actions=[
        {"kind": "sunset", "ref": evil, "unit": "op", "status": "DEPRECATED", "date": "2025-01-01"}]),
        "2026-07-21")
    assert "</script><img" not in html          # the raw sequence never appears literally
    assert _blob(html)["actions"][0]["ref"] == evil   # but the data round-trips intact

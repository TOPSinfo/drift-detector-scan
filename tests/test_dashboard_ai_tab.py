from pathlib import Path

_ASSETS = Path(__file__).resolve().parent.parent / "agent" / "assets"


def test_app_js_consumes_the_leads_blob():
    """render_payload has emitted `leads-data` for some time, but nothing READ it — the blob went
    into the page and no surface showed it."""
    js = (_ASSETS / "dashboard.app.js").read_text()
    assert 'getElementById("leads-data")' in js
    assert "LEADS" in js


def test_ai_plane_has_a_leads_tile():
    js = (_ASSETS / "dashboard.app.js").read_text()
    assert 'label:"Leads"' in js
    assert "leadsCount" in js


def test_the_three_tiers_are_badged_distinctly():
    """One tab, but never one undifferentiated pile: gate-validated shapes, sourced research
    verdicts and unverified leads carry genuinely different trust and the UI must say so."""
    tpl = (_ASSETS / "dashboard.template.html").read_text()
    for badge in ("GATE-VALIDATED", "SOURCED", "UNVERIFIED LEAD"):
        assert badge in tpl, badge


def test_leads_are_never_labelled_certified():
    tpl = (_ASSETS / "dashboard.template.html").read_text()
    i = tpl.find("UNVERIFIED LEAD")
    assert i != -1
    assert "CERTIFIED" not in tpl[i:i + 400]

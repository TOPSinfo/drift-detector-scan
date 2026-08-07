# tests/test_dashboard_assets.py
from pathlib import Path
VENDOR = Path(__file__).resolve().parent.parent / "agent" / "assets" / "vendor"

def test_vue_runtime_is_vendored_and_pinned():
    js = (VENDOR / "vue.global.prod.js").read_text(encoding="utf-8")
    assert len(js) > 50_000                       # the real runtime, not a stub
    assert "Vue" in js                            # exposes the global
    prov = (VENDOR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "vue" in prov.lower() and "http" in prov.lower()   # version + source URL recorded
    import re
    assert re.search(r"\b3\.\d+\.\d+\b", prov)    # a pinned 3.x version string


def test_css_asset_loads_and_is_inlined():
    from agent.lib import dashboard_render as dr
    # Task 1 cockpit-IA restructure: the tile-grid (.tile/.tilegroups) became the primary
    # tab strip (.mtab/.tabstrip) — same token system (--accent etc.), new selector names.
    assert ".mtab" in dr.CSS_SRC and "--accent" in dr.CSS_SRC     # the token system moved intact
    from tests.test_dashboard_render import _inv, _audit
    html = dr.render_dashboard(_inv(), _audit([]), "2026-07-15")
    assert "<style>" in html and ".tabstrip" in html              # still inlined into the page

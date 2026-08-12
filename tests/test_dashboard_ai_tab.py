import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ASSETS = Path(__file__).resolve().parent.parent / "agent" / "assets"
_HARNESS = Path(__file__).resolve().parent / "fixtures" / "leads_harness.js"


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


def test_lead_rows_key_is_not_field_concatenation():
    """Leads are the rawest tier and are often file-level (no `line`) — two leads sharing
    repo+host+file with no line collide on a `:key` built from those fields, which is a silent
    Vue render bug (stale/duplicate DOM nodes on re-render), not a crash you'd notice in tests.
    Every sibling tier (`shaped`, `researchList`, ...) keys its v-for on the loop index instead;
    leadRows must follow that same established pattern."""
    tpl = (_ASSETS / "dashboard.template.html").read_text()
    m = re.search(r'<tr[^>]*v-for="([^"]*) in leadRows"[^>]*:key="([^"]*)"', tpl)
    assert m, "could not find the leadRows v-for row in dashboard.template.html"
    loop_var, key_expr = m.group(1), m.group(2)
    # the loop must destructure an index (mirrors "(sh, si) in shaped", "(rv, ri) in
    # researchList") so a key can be built from it rather than from row fields.
    assert re.match(r"\(\s*\w+\s*,\s*\w+\s*\)", loop_var), (
        "leadRows v-for should destructure an index, e.g. '(r, li) in leadRows', got: %r" % loop_var
    )
    # the key must be built from that index, not concatenated row fields that can collide
    # (repo/host/file with no line).
    assert "r.repo" not in key_expr and "r.file" not in key_expr and "r.line" not in key_expr, (
        "leadRows :key must not concatenate row fields (they can collide) — got: %r" % key_expr
    )


def test_lead_origin_css_rule_is_not_duplicated():
    """Two `.orig[data-origin="lead"]` rules existed — the later one won both `border` and
    `color` outright, so the earlier rule's declarations were fully shadowed dead code."""
    css = (_ASSETS / "dashboard.css").read_text()
    assert css.count('.orig[data-origin="lead"]') == 1


def test_amber_and_muted_badge_tokens_are_defined_in_root():
    """--amber-bg/--amber-fg/--muted-bg/--muted-fg were referenced by the SOURCED/lead badges
    but defined nowhere in :root, so the literal fallbacks always applied and the badges had no
    dark-mode variant — unlike every other colour token in this file."""
    css = (_ASSETS / "dashboard.css").read_text()
    root = css[css.index(":root{"):css.index(":root{") + css[css.index(":root{"):].index("}")]
    for token in ("--amber-bg", "--amber-fg", "--muted-bg", "--muted-fg"):
        assert token + ":" in root, token
        assert "light-dark(" in root[root.index(token + ":"):root.index(token + ":") + 60], token


def _run_leads_computeds(leads_data_text):
    """Actually EXECUTE dashboard.app.js's leadsCount/leadRows computeds (via tests/fixtures/
    leads_harness.js, a minimal document/Vue stub) against a `leads-data` blob, rather than
    grepping the source text. A string-presence assertion cannot see a `.reduce`/`.forEach`
    thrown from inside a Vue computed."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available on PATH")
    proc = subprocess.run(
        [node, str(_HARNESS), leads_data_text],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, (
        "dashboard.app.js threw executing leadsCount/leadRows against %r:\n%s"
        % (leads_data_text, proc.stderr)
    )
    return json.loads(proc.stdout)


@pytest.mark.parametrize("leads_data", [
    '{"repos": "not-an-array"}',
    '{"repos": 5}',
    '{"repos": [{"repo": "x", "integrations": "nope"}]}',
])
def test_leads_computeds_degrade_on_malformed_blob_instead_of_throwing(leads_data):
    """A crashed prior pass, a hand-edited state dir, or a future schema change can leave
    `leads-data` as valid JSON of the wrong shape. `(LEADS.repos || [])` only substitutes `[]`
    when `repos` is falsy — a truthy non-array (a string, a number) or a non-array
    `integrations` one level down flows straight into `.reduce`/`.forEach` and throws inside a
    Vue computed, breaking the whole page render. leadsCount/leadRows must degrade to 0/empty."""
    result = _run_leads_computeds(leads_data)
    assert result == {"leadsCount": 0, "leadRows": []}


def test_leads_computeds_still_work_on_a_wellformed_blob():
    """Guard rails on the malformed cases must not break the happy path."""
    payload = json.dumps({"repos": [{"repo": "demo/repo", "integrations": [
        {"vendor": "Stripe", "host": "api.stripe.com", "endpoint": "/v1/charges",
         "file": "billing.py", "line": 42, "retired": "unknown", "note": "seen in import"},
    ]}]})
    result = _run_leads_computeds(payload)
    assert result["leadsCount"] == 1
    assert result["leadRows"] == [{
        "repo": "demo/repo", "vendor": "Stripe", "host": "api.stripe.com",
        "endpoint": "/v1/charges", "file": "billing.py", "line": 42,
        "retired": "unknown", "note": "seen in import", "origin": "lead",
    }]


def test_leads_computeds_degrade_when_blob_missing():
    """No `leads-data` element at all (the common case — no cross-check has run) must also
    degrade cleanly, not just malformed-but-present blobs."""
    result = _run_leads_computeds("MISSING")
    assert result == {"leadsCount": 0, "leadRows": []}

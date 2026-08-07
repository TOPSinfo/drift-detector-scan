"""The invariants must catch the two bugs that actually shipped.

Each test below RECONSTRUCTS a broken payload exactly as it was produced on 2026-07-20
and asserts the check fires. A guard that cannot be shown to catch its motivating bug is
decoration, so these are written as reproductions first and regressions second.
"""
import json

import pytest

import pytest

from agent.lib import verify
from agent.lib.verify import Violation


def _sunset_finding(op, date, rec, files, domain=None):
    return {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "severity": "SUNSET",
            "status": "DEPRECATED", "operation": op, "domain": domain, "version": None,
            "date": date, "recommendation": rec, "files": files,
            "first_seen": "2026-07-20"}


TWELVE = [
    _sunset_finding("GetCategoryFeatures", "2026-06-04", "migrate to Metadata API",
                    ["src/Ebay/EbayCategoryFieldsFeature.php:72"]),
    _sunset_finding("GetCategories", "2026-04-15", "migrate to Taxonomy API",
                    ["src/Ebay/EbayCategoryFieldsFeature.php:18"]),
    _sunset_finding("AddDispute", "2023-01-27", "migrate to Post-Order API",
                    ["src/Ebay/EbayOrderCancel.php:17"]),
    _sunset_finding(None, "2022-04-30", "migrate to Sell Feed API",
                    ["src/Ebay/src/LMS/ServiceEndpointsAndTokens.php:9"],
                    domain="webservices.ebay.com"),
    _sunset_finding(None, "2022-04-30", "migrate to Sell Feed API",
                    ["src/Ebay/src/LMS/ServiceEndpointsAndTokens.php:12"],
                    domain="storage.ebay.com"),
]


# --------------------------------------------------------------------------- bug #1
def test_tile_count_catches_the_sunset_collapse():
    """SHIPPED BUG: build_actions grouped on (repo, ref), so five retirements with five
    dates became ONE action and the tile read `Sunsets 1`. Tile and table agreed with
    each other — both wrong — which is why nothing caught it. Recomputing from findings
    is the independent path that disagrees."""
    collapsed = {
        "counts": {"sunsets": 1, "eol": 0, "private": 0},
        "actions": [{"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": None,
                     "recommendation": "migrate to Metadata API", "finding_count": 5}],
        "private": [],
    }
    with pytest.raises(Violation) as e:
        verify.check_tile_counts(collapsed, TWELVE)
    assert e.value.check == "sunset-grouping"
    assert "5 distinct" in str(e.value)


def test_tile_count_passes_when_grouped_per_operation():
    ok = {
        "counts": {"sunsets": 5, "eol": 0, "private": 0},
        "actions": [{"repo": "ebayapi", "ref": "eBay", "kind": "sunset",
                     "unit": verify.sunset_unit(f), "recommendation": f["recommendation"],
                     "finding_count": 1} for f in TWELVE],
        "private": [],
    }
    verify.check_tile_counts(ok, TWELVE)          # must not raise


def test_tile_disagreeing_with_its_own_table_is_caught():
    """The simpler half: the number on the tile vs the rows the filter yields."""
    bad = {"counts": {"sunsets": 9, "eol": 0, "private": 0},
           "actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "unit": "X",
                        "recommendation": "y", "finding_count": 1}],
           "private": []}
    with pytest.raises(Violation) as e:
        verify.check_tile_counts(bad, [])
    assert e.value.check == "tile-vs-table"


# --------------------------------------------------------------------------- bug #2
def test_projection_parity_catches_the_dropped_unit_field():
    """SHIPPED BUG: build_actions gained `unit`, but _action_view whitelists fields and
    dropped it, so twelve rows rendered as bare "eBay". The unit test passed because it
    asserted on build_actions output, one layer below what anybody reads."""
    action = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset",
              "unit": "GetCategoryFeatures", "recommendation": "migrate", "fixes": []}
    projected = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset",
                 "recommendation": "migrate"}          # `unit` silently absent
    with pytest.raises(Violation) as e:
        verify.check_projection_parity(action, projected)
    assert e.value.check == "projection-parity"
    assert "unit" in str(e.value)


def test_projection_parity_allows_declared_drops():
    """`fixes` is deliberately not projected (it is the raw finding list). Declaring it
    is what keeps the check honest rather than merely noisy."""
    action = {"repo": "r", "ref": "eBay", "kind": "sunset", "fixes": [1, 2, 3]}
    verify.check_projection_parity(action, {"repo": "r", "ref": "eBay", "kind": "sunset"})


def test_row_labels_must_be_distinct():
    """The reader-facing symptom of bug #2: four rows that look the same."""
    dupes = {"actions": [
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": None,
         "recommendation": "migrate to Sell Feed API before 2022-04-30"},
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": None,
         "recommendation": "migrate to Sell Feed API before 2022-04-30"},
    ]}
    with pytest.raises(Violation) as e:
        verify.check_row_labels_distinct(dupes)
    assert e.value.check == "row-identity"


def test_row_labels_distinct_once_the_host_is_carried():
    ok = {"actions": [
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": "webservices.ebay.com",
         "recommendation": "migrate to Sell Feed API before 2022-04-30"},
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": "storage.ebay.com",
         "recommendation": "migrate to Sell Feed API before 2022-04-30"},
    ]}
    verify.check_row_labels_distinct(ok)


# --------------------------------------------------------------------------- the rail
def test_accessor_coverage_catches_a_field_the_page_reads_but_nothing_emits():
    js = 'var label = a.ref + " " + a.unit; emit(a.repo, a.missingField);'
    with pytest.raises(Violation) as e:
        verify.check_accessor_coverage(js, {"actions": {"ref", "unit", "repo"}})
    assert "missingField" in str(e.value)


def test_blob_parity_detects_a_page_carrying_different_data():
    html = '<script id="drift-data" type="application/json">{"counts":{"sunsets":1}}</script>'
    with pytest.raises(Violation) as e:
        verify.check_blob_matches_payload(html, json.dumps({"counts": {"sunsets": 12}}))
    assert e.value.check == "blob-parity"


def test_blob_parity_tolerates_escaping_and_indentation():
    """The embedded copy escapes `<` and dashboard.json is indented; only the DATA must
    match. Comparing bytes here would fail on a correct pair."""
    payload = {"note": "a <script> tag in scan data"}
    from agent.lib.dashboard_render import _blob
    html = f'<script id="drift-data" type="application/json">{_blob(payload)}</script>'
    verify.check_blob_matches_payload(html, json.dumps(payload, indent=2))


# ------------------------------------------------- wired to the REAL code, not fixtures
def _real_payload():
    from agent.lib.actions import build_actions
    from agent.lib.dashboard_render import build_payload
    actions = build_actions(TWELVE)
    audit = {"generated": "2026-07-20", "findings": TWELVE, "actions": actions,
             "counts": {"reposAffected": 1}}
    inventory = {"repos": [{"path": "ebayapi", "endpoints": [], "sdks": []}],
                 "scope": {"reposScanned": 2}, "coverage": {}}
    return build_payload(inventory, audit), actions


def test_live_projection_parity_over_real_build_actions():
    """The guard that matters: run the REAL action dicts through the REAL projection.
    If someone adds a field to build_actions and forgets the projection, this fails —
    which is precisely what shipped as twelve rows labelled "eBay"."""
    payload, actions = _real_payload()
    assert actions and payload["actions"]
    for action, projected in zip(actions, payload["actions"]):
        verify.check_projection_parity(action, projected)


# The real endpoint/private/catalog row field sets, named explicitly rather than sampled
# from a live row — the payload built by _real_payload() carries no endpoints, no private
# sources and no coverage.catalog (the synthetic inventory/audit above pass none in), so
# there is no live row to pull `set(row)` from the way `payload["actions"][0]` works below.
# Endpoint fields: see _endpoints_of(); private fields: see _build_projection()'s private
# loop; catalog fields: see catalog_coverage.py's record builder.
_ENDPOINT_SAMPLE = {"repo", "domain", "vendor", "version", "classified", "file_count", "files"}
_PRIVATE_SAMPLE = {"repo", "source", "kind", "via"}
_CATALOG_SAMPLE = {"vendor", "callSites", "catalogEntries", "verdict", "reasons", "checked", "source"}


def _row_union(payload):
    """The allowed set for the Vue summary table's polymorphic `row` loop var: the union of
    all four row shapes it can render (mode is actions | endpoints | private | catalog)."""
    return set(payload["actions"][0]) | _ENDPOINT_SAMPLE | _PRIVATE_SAMPLE | _CATALOG_SAMPLE


def test_live_accessor_coverage_over_the_real_client_js():
    """Every a.field / e.field / p.field / cv.field / row.field the shipped page reads must
    exist in the real payload.

    Since the Task 3 re-platform, the client is the in-DOM Vue template + the app skeleton
    (accessors now live in both — the guard itself is a pure regex over a string, so it is
    fed the concatenation of the two sources rather than the old server-built _CLIENT_JS).
    `row` (the polymorphic summary-table loop var) is checked against the union of all four
    row shapes — actions/endpoints/private/catalog — since the same template renders all
    four depending on `mode`."""
    from agent.lib import dashboard_render as _dr
    _CLIENT_SRC = _dr.TEMPLATE_SRC + "\n" + _dr.APP_JS_SRC
    payload, _ = _real_payload()
    verify.check_accessor_coverage(_CLIENT_SRC, {
        "actions": set(payload["actions"][0]),
        # this fixture's inventory carries no endpoints/private rows (empty lists), so
        # there is nothing live to sample for the independent "e."/"p." checks — unchanged
        # from before this fix. The "row" union below still covers their fields via the
        # named _ENDPOINT_SAMPLE/_PRIVATE_SAMPLE constants, independently of these two.
        "endpoints": set(payload["endpoints"][0]) if payload.get("endpoints") else None,
        "private": set(payload["private"][0]) if payload.get("private") else None,
        "catalog": _CATALOG_SAMPLE,
        "row": _row_union(payload),
    })


def test_accessor_coverage_does_not_false_positive_on_sbom_property_loop():
    # regression: componentRepos() must not use `p` for SBOM component properties — `p` is the
    # reserved accessor-coverage letter for PRIVATE rows, so `p.name`/`p.value` would be read as
    # bogus private fields and raise spuriously once a real private sample set is checked.
    from agent.lib import dashboard_render as dr
    from agent.lib import verify
    src = dr.TEMPLATE_SRC + "\n" + dr.APP_JS_SRC
    # the actual fields a private row carries (see _build_projection)
    verify.check_accessor_coverage(src, {"private": {"repo", "source", "kind", "via"}})
    # (no raise == pass)


def test_accessor_coverage_catches_a_bogus_summary_row_field():
    """PROVE THE BUG: post-Vue-port, the summary table's row loop var (renamed `r` -> `row`
    in this fix) went UNGUARDED, because _ACCESSOR only tracked a|e|p|cv — a typo'd or
    renamed display field like `{{ row.bogusField }}` would render a blank column with
    nothing failing. This reconstructs exactly that against the real union of
    action/endpoint/private/catalog fields the row loop is checked against."""
    from agent.lib import dashboard_render as dr
    bogus_snippet = '<template v-for="(row, idx) in rows"><td>{{ row.bogusField }}</td></template>'
    payload, _ = _real_payload()
    with pytest.raises(Violation) as e:
        verify.check_accessor_coverage(dr.APP_JS_SRC + "\n" + bogus_snippet,
                                       {"row": _row_union(payload)})
    assert e.value.check == "accessor-coverage"
    assert "bogusField" in str(e.value)


def test_accessor_coverage_passes_on_the_real_summary_table_row_fields():
    """Positive control for the same guard: every real `row.field` in the shipped template
    exists in the union of action/endpoint/private/catalog fields, so the r -> row rename
    did not silently drop coverage over the 26-odd display fields the summary table reads."""
    from agent.lib import dashboard_render as dr
    payload, _ = _real_payload()
    verify.check_accessor_coverage(dr.TEMPLATE_SRC + "\n" + dr.APP_JS_SRC,
                                   {"row": _row_union(payload)})


def test_live_invariants_hold_on_the_real_payload():
    payload, _ = _real_payload()
    assert verify.verify_payload(payload, TWELVE) == []


# ------------------------------------------------------------------- the owner split
def test_owner_split_holds_on_the_real_payload():
    """Every sunset is a developer job; the per-owner counts must reflect that and the
    integrity check must pass on the honest payload."""
    payload, _ = _real_payload()
    verify.check_owner_split(payload)                      # must not raise
    by = payload["counts"]["byOwner"]
    dep = sum(1 for a in payload["actions"] if a["status"] == "DEPRECATED")
    assert by["developer"]["fixes"] == dep and by["devops"]["fixes"] == 0


def test_owner_integrity_catches_a_mislabelled_action():
    """A routing bug that sends a developer's API migration to the DevOps board must be
    caught: the stored owner disagrees with owners.owner() recomputed from the action."""
    payload, _ = _real_payload()
    payload["actions"][0]["owner"] = "devops"             # a sunset is developer work
    with pytest.raises(Violation) as e:
        verify.check_owner_split(payload)
    assert e.value.check == "owner-integrity"


def test_owner_count_parity_catches_a_miscount():
    """If a queue's tally drifts from its actions, the two streams disagree with the data."""
    payload, _ = _real_payload()
    payload["counts"]["byOwner"]["developer"]["fixes"] += 1
    with pytest.raises(Violation) as e:
        verify.check_owner_split(payload)
    assert e.value.check == "owner-count-parity"


def test_live_blob_parity_between_html_and_payload():
    """dashboard.html embeds exactly the payload dashboard.json holds."""
    from agent.lib.dashboard_render import render_payload
    payload, _ = _real_payload()
    verify.check_blob_matches_payload(render_payload(payload, "2026-07-20"),
                                      json.dumps(payload))


# ------------------------------------------------------------------ the CLI entrypoint
def test_drift_verify_cli_passes_clean_and_fails_tampered(tmp_path, capsys):
    """`drift-scan verify` is the claim the assistant is allowed to make. It must exit 0
    on a consistent report and 3 on an inconsistent one — never the reverse."""
    from agent.cli import main
    from agent.lib.dashboard_render import render_payload
    from agent.lib.md_render import render_markdown
    payload, _ = _real_payload()
    (tmp_path / "drift.json").write_text(json.dumps(payload, indent=2))
    (tmp_path / "audit.json").write_text(json.dumps({"findings": TWELVE}))
    (tmp_path / "dashboard.html").write_text(render_payload(payload, "2026-07-20"))
    (tmp_path / "drift.md").write_text(render_markdown(payload, "2026-07-20"))

    assert main(["verify", "--state", str(tmp_path)]) == 0

    # tamper exactly as bug #1 presented: the tile disagrees with its table
    bad = json.loads((tmp_path / "drift.json").read_text())
    bad["counts"]["sunsets"] = 1
    (tmp_path / "drift.json").write_text(json.dumps(bad, indent=2))
    assert main(["verify", "--state", str(tmp_path)]) == 3
    assert "tile-vs-table" in capsys.readouterr().out


def test_drift_verify_reports_nothing_to_verify_rather_than_passing(tmp_path):
    """An absent report must never read as a clean one — the same 'cannot check is not
    clean' rule the --fail-on-deprecated gate already follows (exit 4)."""
    from agent.cli import main
    assert main(["verify", "--state", str(tmp_path)]) == 4


# ------------------------------------------------------- the UNAUDITED tile obeys the rail
def test_unaudited_tile_must_match_its_own_panel():
    """The new tile is held to the same rule as every other: the number equals the rows.
    Added WITH the feature, not after a user reports four identical rows."""
    bad = {"counts": {"sunsets": 0, "eol": 0, "private": 0, "unaudited": 3},
           "actions": [], "private": [],
           "catalog": [{"vendor": "eBay", "verdict": "UNAUDITED", "callSites": 162},
                       {"vendor": "Amazon SP-API", "verdict": "CURRENT", "callSites": 272}]}
    with pytest.raises(Violation) as e:
        verify.check_tile_counts(bad, [])
    assert e.value.check == "tile-vs-table"
    assert "unaudited" in str(e.value)


def test_unaudited_tile_excludes_current_vendors():
    """A vendor whose page WAS checked is not a gap and must not inflate the tile."""
    ok = {"counts": {"sunsets": 0, "eol": 0, "private": 0, "unaudited": 1},
          "actions": [], "private": [],
          "catalog": [{"vendor": "eBay", "verdict": "UNAUDITED", "callSites": 162},
                      {"vendor": "Amazon SP-API", "verdict": "CURRENT", "callSites": 272}]}
    verify.check_tile_counts(ok, [])


def test_catalog_accessor_coverage_over_the_real_client_js():
    """renderCatalog reads r.vendor / r.verdict / r.callSites — all must exist.

    (Same Task 3 re-pointing as above: the catalog-rendering JS is Task 4/5 territory and
    reads no `cv.field` yet, so this currently holds vacuously — it activates the moment
    that renderer is (re)written against the Vue app.)"""
    from agent.lib import dashboard_render as _dr
    _CLIENT_SRC = _dr.TEMPLATE_SRC + "\n" + _dr.APP_JS_SRC
    verify.check_accessor_coverage(_CLIENT_SRC, {"catalog": {
        "vendor", "verdict", "callSites", "catalogEntries", "checked", "reasons", "source"}})


# ------------------------------------------------- number-format determinism (port insurance)
def test_number_format_passes_on_clean_numbers():
    from agent.lib.verify import check_number_formats
    check_number_formats({"counts": {"fixes": 6}, "score": 7.5,          # int + one-decimal float
                          "rows": [{"n": 0}, {"n": 12}], "flag": True})   # bools are not numbers


def test_number_format_catches_a_multi_decimal_float():
    import pytest
    from agent.lib.verify import check_number_formats, Violation
    with pytest.raises(Violation) as e:
        check_number_formats({"a": {"b": 7.55}})
    assert e.value.check == "number-format" and "7.55" in str(e.value)


def test_number_format_catches_scientific_notation():
    import pytest
    from agent.lib.verify import check_number_formats, Violation
    # 1e16 / 3e-05 are the exact values Python and Go format differently
    for bad in (1e16, 3e-05):
        with pytest.raises(Violation):
            check_number_formats({"x": bad})


def test_number_format_holds_on_the_real_payload():
    from agent.lib.verify import check_number_formats
    from tests.test_verify import _real_payload
    payload, _ = _real_payload()
    check_number_formats(payload)                     # the live payload must already comply


def test_verify_fails_when_an_unscannable_root_is_dropped_from_the_report():
    """Reproduces the shipped bug: the payload knows a root it couldn't read, but the
    Markdown never names it. verify must catch that, not pass it green."""
    from agent.lib import verify
    payload = {"counts": {"unscannable": 1},
               "rootsUnscannable": [{"root": "https://git.x/team/ghost", "reason": "404"}]}
    md_that_drops_it = "# Drift report\n\nAll clean.\n"
    with pytest.raises(verify.Violation):
        verify.check_unscannable_surfaced(md_that_drops_it, payload)


def test_verify_passes_when_the_unscannable_root_is_named():
    from agent.lib import verify
    payload = {"counts": {"unscannable": 1},
               "rootsUnscannable": [{"root": "https://git.x/team/ghost", "reason": "404"}]}
    md_that_names_it = "# Drift report\n\n## Couldn't scan\n\nhttps://git.x/team/ghost — 404\n"
    verify.check_unscannable_surfaced(md_that_names_it, payload)   # no raise


# ------------------------------------------------- the Retirement Timeline structural guard
def test_timeline_lanes_guard_flags_a_missing_undated_lane():
    """PROVE THE BUG: the former check_chart_parity(payload) asserted
    len(dated)+len(undated) == counts.sunsets, which is a tautology — dated/undated are an
    exhaustive partition of the same sunset list by construction, so it holds no matter what
    the template renders and never looked at the client at all. It would stay green even if a
    future edit deleted the undated lane from the page, silently hiding every
    deprecated-no-date sunset (a 'cannot see != clean' honesty regression). This reconstructs
    that exact edit — a template that renders the dated axis but not the undated lane — and
    the new structural guard must catch it."""
    template_missing_undated = (
        '<g v-for="(pt, i) in timeline.dated" :key="\'d\' + i" class="tl-point">'
        '<circle :cx="pt.x" :cy="130" r="8" :fill="pt.color"></circle></g>'
    )
    with pytest.raises(Violation) as e:
        verify.check_timeline_lanes(template_missing_undated)
    assert e.value.check == "timeline-lanes"
    assert "timeline.undated" in str(e.value)


def test_timeline_lanes_guard_passes_on_the_real_template():
    from agent.lib import dashboard_render as dr
    verify.check_timeline_lanes(dr.TEMPLATE_SRC)     # both lanes present -> no raise


def test_timeline_lanes_guard_matches_the_new_per_operation_markup():
    """Task 2: the timeline was rewritten from a per-vendor SVG scatter into per-operation
    `.trk` rows grouped by vendor (`timeline.byVendor`), plus an undated lane
    (`timeline.undated`). The guard must keep working against THIS markup, not just the
    retired SVG one — reconstruct the exact edit that would silently drop the undated lane
    from the new template and prove the guard still catches it."""
    from agent.lib import dashboard_render as dr
    verify.check_timeline_lanes(dr.TEMPLATE_SRC)                 # real template passes
    bad = dr.TEMPLATE_SRC.replace("timeline.undated", "timeline.dated")  # drop the undated lane
    try:
        verify.check_timeline_lanes(bad)
        assert False, "expected a Violation"
    except verify.Violation as v:
        assert v.check == "timeline-lanes"


def test_verify_catches_a_stale_or_tampered_sbom():
    """A verified projection: sbom.json must equal a fresh build from inventory+audit. A
    hand-edited BOM (dropped component/vuln) must fail, or the SBOM isn't trustworthy."""
    from agent.lib import verify, sbom
    inv = {"repos": [{"path": "r", "sdks": [{"eco": "npm", "pkg": "axios", "resolved": "0.21.1"}]}]}
    audit = {"findings": []}
    good = sbom.build_sbom(inv, audit, "2026-07-27")
    verify.check_sbom_matches_inventory(good, inv, audit)          # no raise
    tampered = {**good, "components": []}                           # someone dropped the parts list
    with pytest.raises(verify.Violation):
        verify.check_sbom_matches_inventory(tampered, inv, audit)

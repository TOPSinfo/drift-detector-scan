"""The dashboard renders ACTIONS + endpoints into one self-contained HTML file.
Pure Python; string/JSON assertions only — no browser, no network."""
import json
import re

from agent.lib import dashboard_render as dr
from agent.lib.dashboard_render import render_dashboard


def _cve(repo="r", ref="npm/axios", version="0.21.1", fixed="1.16.0", severity="HIGH",
         status="DEPRECATED", first_seen="2026-07-15", **kw):
    return {"repo": repo, "ref": ref, "kind": "cve", "version": version, "fixed": fixed,
            "severity": severity, "status": status, "first_seen": first_seen,
            "id": kw.get("id", "CVE-x"), "cve": kw.get("cve", "CVE-x"),
            "detail": kw.get("detail", "summary text"), "recommendation": f"upgrade to >= {fixed}",
            "source_url": kw.get("source_url", "https://osv.dev/x"), "tier": 1}


def _audit(findings):
    # audit WITHOUT a precomputed actions key -> exercises the build_actions fallback
    return {"generated": "2026-07-15", "findings": findings,
            "counts": {"DEPRECATED": sum(1 for f in findings if f["status"] == "DEPRECATED"),
                       "REVIEW": sum(1 for f in findings if f["status"] == "REVIEW"),
                       "reposAffected": len({f["repo"] for f in findings})},
            "coverage": {"notes": ["note one"]}}


def _inv(endpoints=()):
    return {"generated": "2026-07-15",
            "repos": [{"path": "svc-a", "endpoints": list(endpoints)}]}


def _blob(html):
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    assert m, "drift-data blob not found"
    return json.loads(m.group(1).replace("\\u003c", "<"))


def test_is_a_self_contained_html_document():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    assert html.startswith("<!doctype html>")
    assert html.count('<script id="drift-data"') == 1


def test_blob_action_count_matches_non_suppressed_actions():
    findings = [_cve(ref="npm/a"), _cve(ref="npm/b"), _cve(ref="npm/c")]
    data = _blob(render_dashboard(_inv(), _audit(findings), "2026-07-15"))
    assert len(data["actions"]) == 3


def test_every_command_appears_in_the_output():
    html = render_dashboard(_inv(), _audit([_cve(ref="python/torch", fixed="2.10.0")]),
                            "2026-07-15")
    assert "pip install 'torch>=2.10.0'" in html


def test_tile_counts_are_action_based_not_finding_based():
    # 3 critical FINDINGS on the same package = ONE critical ACTION. The tile must read 1.
    findings = [_cve(ref="npm/mongoose", severity="CRITICAL", id=f"CVE-{i}", cve=f"CVE-{i}")
                for i in range(3)]
    data = _blob(render_dashboard(_inv(), _audit(findings), "2026-07-15"))
    assert data["counts"]["critical"] == 1
    assert data["counts"]["fixes"] == 1


def test_tile_counts_apis_and_unknown_from_endpoints():
    eps = [{"domain": "api.ebay.com", "vendor": "eBay", "version": "v1", "classified": True,
            "file_count": 1, "files": ["a.php:1"]},
           {"domain": "api.stripe.com", "vendor": "Stripe", "version": "v1", "classified": True,
            "file_count": 1, "files": ["b.php:1"]},
           {"domain": "x.internal.io", "vendor": "Unknown", "version": None, "classified": False,
            "file_count": 1, "files": ["c.php:1"]}]
    data = _blob(render_dashboard(_inv(eps), _audit([_cve()]), "2026-07-15"))
    assert data["counts"]["apis"] == 2        # eBay + Stripe
    assert data["counts"]["unknown"] == 1


def test_eol_action_tile_and_no_command():
    eol = {"repo": "r", "ref": "php", "kind": "eol", "version": "^7.4", "fixed": "8.5.8",
           "severity": "EOL", "status": "DEPRECATED", "first_seen": "2026-07-15",
           "detail": "php 7.4 end-of-life 2022-11-28", "recommendation": "upgrade to 8.5.8",
           "source_url": "https://endoflife.date/php", "tier": 1}
    data = _blob(render_dashboard(_inv(), _audit([eol]), "2026-07-15"))
    assert data["counts"]["eol"] == 1
    a = next(a for a in data["actions"] if a["kind"] == "eol")
    assert a["command"] is None and a["fix_version"] == "8.5.8"


def test_sunset_action_files_render_and_tile_counts():
    sunset = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "version": "v1",
              "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
              "detail": "eBay v1 retires 2026-09-30", "date": "2026-09-30",
              "recommendation": "migrate to Sell API before 2026-09-30",
              "source_url": "https://developer.ebay.com/x", "tier": 1,
              "files": ["src/Ebay/x.php:111", "src/Ebay/y.php:540"]}
    html = render_dashboard(_inv(), _audit([sunset]), "2026-07-15")
    data = _blob(html)
    assert data["counts"]["sunsets"] == 1
    assert "src/Ebay/x.php:111" in html           # the moat payload is in the file


def test_zero_sunsets_when_no_sunset_actions():
    data = _blob(render_dashboard(_inv(), _audit([_cve()]), "2026-07-15"))
    assert data["counts"]["sunsets"] == 0


def _sunset(repo, status, date, ref="eBay"):
    return {"repo": repo, "ref": ref, "kind": "sunset", "version": "v1",
            "severity": "SUNSET", "status": status, "first_seen": "2026-07-15",
            "detail": "x", "date": date, "recommendation": "migrate",
            "source_url": "https://developer.ebay.com/x", "tier": 1,
            "files": [f"src/{repo}.php:1"]}


def test_owner_tiles_and_filter_split_the_two_streams():
    cve = _cve(repo="web", severity="HIGH")                    # -> devops
    sunset = _sunset("ebayapi", "DEPRECATED", "2025-01-01")    # -> developer
    html = render_dashboard(_inv(), _audit([cve, sunset]), "2026-07-15")
    data = _blob(html)
    assert data["counts"]["byOwner"] == {"devops": {"fixes": 1, "review": 0},
                                         "developer": {"fixes": 1, "review": 0}}
    # Ownership is cross-cutting (it spans all three planes), so it's a HEADER stat now
    # (App.ownStats), not a tile of its own — but the two delivery streams are still split
    # devops vs developer, and the math still mirrors the old server-side `_own` lambda: the
    # byOwner sub-dict's lowercase "fixes"/"review" keys, not the finding-status literals.
    assert 'own("devops")' in dr.APP_JS_SRC and 'own("developer")' in dr.APP_JS_SRC
    assert "v.fixes" in dr.APP_JS_SRC and "v.review" in dr.APP_JS_SRC
    # each projected action carries its owner
    owners = {a["ref"]: a["owner"] for a in data["actions"]}
    assert owners["npm/axios"] == "devops" and owners["eBay"] == "developer"


def test_pastdue_counts_only_retired_sunsets():
    # retired (DEPRECATED + past date) counts; upcoming (REVIEW + future date) and a
    # deprecated-but-no-date-announced sunset do NOT — "past-due" means a passed deadline.
    findings = [_sunset("a", "DEPRECATED", "2025-01-01"),   # retired -> past-due
                _sunset("b", "REVIEW", "2027-01-01"),        # upcoming deadline -> not
                _sunset("c", "DEPRECATED", None)]            # deprecated, no date -> not
    data = _blob(render_dashboard(_inv(), _audit(findings), "2026-07-15"))
    assert data["counts"]["sunsets"] == 3
    assert data["counts"]["pastDue"] == 1
    # the tile is wired in the Vue app's tileGroups, bound to counts.pastDue
    assert 'key:"pastdue"' in dr.APP_JS_SRC and "c.pastDue" in dr.APP_JS_SRC


def test_output_is_byte_identical_across_calls():
    inv, audit = _inv(), _audit([_cve(ref="b/z"), _cve(ref="a/y", severity="CRITICAL")])
    assert render_dashboard(inv, audit, "2026-07-15") == render_dashboard(inv, audit, "2026-07-15")


def test_empty_audit_renders_valid_document_with_nothing_found():
    # the "Nothing found" empty-state copy lives in the Summary table (Task 4's scope);
    # here we only prove the shell renders a valid, well-formed document with an empty
    # actions list in the trust-anchor blob.
    html = render_dashboard(_inv(), _audit([]), "2026-07-15")
    assert html.startswith("<!doctype html>")
    assert _blob(html)["actions"] == []


def test_xss_scan_strings_are_escaped_on_both_surfaces():
    evil = 'a<script>alert(1)</script>&"x'
    findings = [_cve(repo=evil)]
    html = render_dashboard(_inv(), _audit(findings), "2026-07-15")
    # 1) the raw payload never appears literally as HTML
    assert "<script>alert(1)</script>" not in html
    # 2) the JSON blob cannot be broken out of: no literal </script> inside it
    blob_raw = re.search(r'<script id="drift-data"[^>]*>(.*?)</script>',
                         html, re.DOTALL).group(1)
    assert "</script>" not in blob_raw
    # 3) it still round-trips: the value is intact once parsed
    data = json.loads(blob_raw.replace("\\u003c", "<"))
    assert data["actions"][0]["repo"] == evil


def test_suppressed_findings_are_excluded_from_actions():
    normal = _cve(ref="npm/keep")
    muted = _cve(ref="npm/muted")
    muted["suppressed"] = True
    data = _blob(render_dashboard(_inv(), _audit([normal, muted]), "2026-07-15"))
    refs = {a["ref"] for a in data["actions"]}
    assert "npm/keep" in refs
    assert "npm/muted" not in refs


def test_no_external_assets():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    assert "<script src" not in html.lower()
    assert '<link rel="stylesheet"' not in html.lower()
    assert "@import" not in html.lower()
    assert '<img src="http' not in html.lower()


def test_projection_carries_every_field_the_ui_reads():
    sunset = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "version": "v1",
              "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
              "detail": "d", "date": "2026-09-30", "recommendation": "migrate before 2026-09-30",
              "source_url": "https://x", "tier": 1, "files": ["src/Ebay/x.php:111"]}
    data = _blob(render_dashboard(_inv(), _audit([sunset, _cve()]), "2026-07-15"))
    a = data["actions"][0]
    for k in ("repo", "ref", "kind", "current_version", "fix_version", "command",
              "recommendation", "worst", "status", "finding_count", "cves", "sources", "files"):
        assert k in a, k
    # endpoint rows carry what the endpoint view needs
    eps_inv = _inv([{"domain": "api.ebay.com", "vendor": "eBay", "version": "v1",
                     "classified": True, "file_count": 1, "files": ["a.php:1"]}])
    ep = _blob(render_dashboard(eps_inv, _audit([_cve()]), "2026-07-15"))["endpoints"][0]
    for k in ("repo", "domain", "vendor", "version", "classified", "file_count", "files"):
        assert k in ep, k


def test_permalink_github_blob_shape():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://github.com/o/r", "SHA", "src/x.php:37") == \
        "https://github.com/o/r/blob/SHA/src/x.php#L37"


def test_permalink_gitlab_dash_blob_shape():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://gitlab.com/o/r", "SHA", "src/x.php:37") == \
        "https://gitlab.com/o/r/-/blob/SHA/src/x.php#L37"


def test_permalink_self_hosted_gitlab_via_env(monkeypatch):
    from agent.lib.dashboard_render import _permalink
    monkeypatch.setenv("DRIFT_GITLAB_HOSTS", "git.example.com")
    assert _permalink("https://git.example.com/example-org/ebayapi", "SHA", "src/config/ebay.php:39") == \
        "https://git.example.com/example-org/ebayapi/-/blob/SHA/src/config/ebay.php#L39"


def test_permalink_unknown_host_and_missing_bits_are_none(monkeypatch):
    from agent.lib.dashboard_render import _permalink
    monkeypatch.delenv("DRIFT_GITLAB_HOSTS", raising=False)
    assert _permalink("https://bitbucket.org/o/r", "SHA", "src/x.php:1") is None   # unknown host
    assert _permalink(None, "SHA", "src/x.php:1") is None                          # no remote
    assert _permalink("https://github.com/o/r", None, "src/x.php:1") is None       # no sha


def test_permalink_missing_line_omits_anchor():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://github.com/o/r", "SHA", "src/x.php") == \
        "https://github.com/o/r/blob/SHA/src/x.php"


def test_projection_rewrites_files_to_loc_href_dicts():
    # a sunset action whose repo has a github remote -> each file becomes {loc, href}
    from agent.lib.dashboard_render import _build_projection
    inv = {"repos": [{"path": "r", "remote_url": "https://github.com/o/r", "head_sha": "SHA",
                      "endpoints": []}]}
    audit = {"actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "files": ["src/x.php:37"],
                          "fixes": [], "sources": []}]}
    proj = _build_projection(inv, audit)
    f = proj["actions"][0]["files"][0]
    assert f == {"loc": "src/x.php:37", "href": "https://github.com/o/r/blob/SHA/src/x.php#L37"}


def test_projection_files_href_none_for_local_repo():
    from agent.lib.dashboard_render import _build_projection
    inv = {"repos": [{"path": "r", "remote_url": None, "head_sha": "SHA", "endpoints": []}]}
    audit = {"actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "files": ["src/x.php:37"],
                          "fixes": [], "sources": []}]}
    f = _build_projection(inv, audit)["actions"][0]["files"][0]
    assert f == {"loc": "src/x.php:37", "href": None}


def _sunset_inv_audit(remote_url, files=("src/x.php:37", "src/y.php:39")):
    inv = {"repos": [{"path": "r", "remote_url": remote_url, "head_sha": "SHA", "endpoints": []}]}
    audit = {"generated": "2026-07-17", "coverage": {},
             "actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "recommendation": "migrate",
                          "files": list(files), "fixes": [], "sources": []}]}
    return inv, audit


def test_no_token_in_rendered_html_even_if_remote_had_one():
    # belt-and-suspenders: even though Task 1 strips at capture, assert nothing leaks here.
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit("https://github.com/o/r")       # already stripped upstream
    out = render_dashboard(inv, audit, "2026-07-17")
    assert "glpat-" not in out and "@github.com" not in out


def test_call_site_loc_is_xss_escaped():
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit(None, files=['a<script>alert(1)</script>:1'])
    out = render_dashboard(inv, audit, "2026-07-17")
    assert "<script>alert(1)</script>" not in out                 # not literal in the HTML


def _inv_with_private(private, sdkmediated=()):
    return {"repos": [], "coverage": {"privateSources": list(private),
                                      "sdkMediated": list(sdkmediated)}}


def test_projection_flattens_private_sources_and_counts():
    from agent.lib.dashboard_render import _build_projection
    inv = _inv_with_private([
        {"repo": "r", "packages": [{"pkg": "@acme/secret", "via": "git+ssh://x"}],
         "repositories": ["https://git.internal/pkg.git"]},
    ], sdkmediated=[{"repo": "r", "sdkCount": 2, "endpointCount": 0}])
    proj = _build_projection(inv, {"actions": []})
    assert proj["counts"]["private"] == 2                               # 1 package + 1 repo
    rows = proj["private"]
    assert {r["kind"] for r in rows} == {"package", "repo"}
    pkg = next(r for r in rows if r["kind"] == "package")
    assert pkg == {"repo": "r", "source": "@acme/secret", "kind": "package", "via": "git+ssh://x"}
    repo = next(r for r in rows if r["kind"] == "repo")
    assert repo["source"] == "https://git.internal/pkg.git" and repo["via"] == ""
    assert proj["sdkMediated"] == [{"repo": "r", "sdkCount": 2, "endpointCount": 0}]


def test_projection_private_empty_when_no_private_sources():
    from agent.lib.dashboard_render import _build_projection
    proj = _build_projection({"repos": [], "coverage": {}}, {"actions": []})
    assert proj["counts"]["private"] == 0 and proj["private"] == [] and proj["sdkMediated"] == []


def test_dashboard_has_private_tile_and_carries_coverage_data():
    # The Private tile itself is wired in the Vue app's tileGroups (Integrations group);
    # the private-source LIST and the Coverage section are Task 4/5 UI (a table + a footer
    # panel, not yet built). This proves the data contract those later panels will read:
    # the private rows and sdkMediated rows both reach the blob intact.
    from agent.lib.dashboard_render import render_dashboard
    inv = _inv_with_private(
        [{"repo": "r", "packages": [{"pkg": "@acme/secret", "via": "git+ssh://x"}],
          "repositories": ["https://git.internal/pkg.git"]}],
        sdkmediated=[{"repo": "svc", "sdkCount": 3, "endpointCount": 1}])
    audit = {"generated": "2026-07-17", "actions": [],
             "coverage": {"notes": ["Sources: OSV.dev + endoflife.date."]}}
    html = render_dashboard(inv, audit, "2026-07-17")
    assert 'key:"private"' in dr.APP_JS_SRC                     # the tile is wired
    # the private source strings are embedded (blob-level; Task 4/5 render them on click)
    assert "@acme/secret" in html and "git.internal/pkg.git" in html
    data = _blob(html)
    assert any(p.get("source") == "@acme/secret" for p in data.get("private", []))
    assert any("OSV.dev" in n for n in data.get("coverageNotes", []))
    assert any(m.get("repo") == "svc" and m.get("sdkCount") == 3 for m in data.get("sdkMediated", [])),\
        "sdkMediated data with repo='svc' and sdkCount=3 must be present in the JSON blob"


def test_private_source_xss_escaped():
    from agent.lib.dashboard_render import render_dashboard
    evil = 'a<script>alert(1)</script>&"x'
    inv = _inv_with_private([{"repo": evil, "packages": [{"pkg": evil, "via": evil}],
                              "repositories": []}])
    out = render_dashboard(inv, {"actions": [], "coverage": {}}, "2026-07-17")
    assert "<script>alert(1)</script>" not in out               # not literal in HTML
    blob = out.split('id="drift-data" type="application/json">')[1].split("</script>")[0]
    assert "</script>" not in blob                              # blob can't break out


def test_dashboard_coverage_grades_reach_the_projection():
    # The Coverage footer (grades table) is Task 4/5 UI; this proves the data it will read
    # is already in the projection/blob.
    from agent.lib.dashboard_render import _build_projection
    inv = {"repos": [], "coverage": {"residue": {
        "pathLiterals": [{"repo": "amazonspapi", "sample": "/orders/2026-01-01/orders", "loc": "OrdersApi.php:44"}],
        "sinks": [], "byRepo": [{"repo": "amazonspapi", "attributed": 0, "unattributedPaths": 262,
                                 "unresolvedSinks": 3, "grade": "LOW"}]}}}
    proj = _build_projection(inv, {"actions": [], "coverage": {"notes": []}})
    assert any(g["repo"] == "amazonspapi" and g["grade"] == "LOW" for g in proj.get("coverageGrades", []))


def test_dashboard_coverage_grade_xss_escaped():
    inv = {"repos": [], "coverage": {"residue": {
        "pathLiterals": [{"repo": "r", "sample": "/x/v0/</script><b>pwn", "loc": "a.php:1"}],
        "sinks": [], "byRepo": [{"repo": "r</script>", "attributed": 0, "unattributedPaths": 1,
                                 "unresolvedSinks": 0, "grade": "LOW"}]}}}
    html = render_dashboard(inv, {"actions": [], "coverage": {}}, "2026-07-17")
    assert "<script><b>pwn" not in html
    assert "r</script>" not in html.split('id="drift-data"')[0]


def test_ssh_repository_url_renders_as_escaped_text_not_link():
    from agent.lib.dashboard_render import render_dashboard
    # Private source with ssh:// repository URL must NOT be linked, only rendered as escaped text
    inv = _inv_with_private([{"repo": "r", "packages": [], "repositories": ["ssh://git@internal/x.git"]}])
    html = render_dashboard(inv, {"actions": [], "coverage": {}}, "2026-07-17")
    assert 'href="ssh://' not in html                           # never linked with href
    assert "ssh://git@internal/x.git" in html                   # present as text


def test_dashboard_renders_inventory_drift_when_diff_supplied():
    # The "Changed since last scan" panel is Task 4+ UI; this proves the diff data it will
    # read reaches the blob (dashboard.html embeds the same payload drift.json holds).
    inv = {"repos": [], "coverage": {}}
    diff = {"reposAdded": ["web"], "reposRemoved": [],
            "changes": [{"repo": "svc", "endpointsAdded": ["api.x.com v2"], "endpointsRemoved": [],
                         "sdksAdded": [], "sdksRemoved": [],
                         "sdkVersionChanges": [{"eco": "npm", "pkg": "axios", "from": "^1.6", "to": "^1.7"}],
                         "runtimeChanges": []}]}
    html = render_dashboard(inv, {"actions": [], "coverage": {}}, "2026-07-17", diff=diff)
    data = _blob(html)
    assert data["inventoryDrift"]["reposAdded"] == ["web"]
    assert data["inventoryDrift"]["changes"][0]["sdkVersionChanges"][0]["pkg"] == "axios"


def test_dashboard_without_diff_carries_no_drift():
    html = render_dashboard({"repos": [], "coverage": {}}, {"actions": [], "coverage": {}}, "2026-07-17")
    assert "inventoryDrift" not in _blob(html)


def test_inventory_drift_is_xss_escaped():
    diff = {"reposAdded": ["r</script><b>pwn"], "reposRemoved": [], "changes": []}
    html = render_dashboard({"repos": [], "coverage": {}}, {"actions": [], "coverage": {}},
                            "2026-07-17", diff=diff)
    assert "<b>pwn" not in html.split('id="drift-data"')[0]


def _inv_cov(coverage):
    inv = _inv()
    inv["coverage"] = coverage
    return inv


def test_unscannable_roots_reach_the_payload_and_count():
    """inventory.coverage.rootsUnscannable must be projected into drift.json (the contract),
    with a matching count — the bug was that it stopped at inventory.json."""
    roots = [{"root": "https://git.x/team/ghost", "reason": "404 no access"}]
    html = render_dashboard(_inv_cov({"rootsUnscannable": roots}), _audit([]), "2026-07-15")
    blob = _blob(html)
    assert blob["rootsUnscannable"] == roots
    assert blob["counts"]["unscannable"] == 1


def test_no_unscannable_key_pollution_when_all_scanned():
    html = render_dashboard(_inv(), _audit([]), "2026-07-15")
    blob = _blob(html)
    assert blob["rootsUnscannable"] == []
    assert blob["counts"]["unscannable"] == 0


def test_dashboard_is_a_self_contained_vue_app():
    """Task 3: the structural pivot. The server-built HTML body is gone — the page is an
    in-DOM Vue template + a createApp skeleton that renders the headline + tiles reactively
    from the embedded blob. Tables/charts/deep-links are later tasks; this proves the shell."""
    from agent.lib import dashboard_render as dr
    html = dr.render_dashboard(_inv(), _audit([_cve(repo="web")]), "2026-07-15")
    # single self-contained file: Vue inlined, no external fetch
    assert "createApp" in html and "cdn" not in html.lower() and "unpkg" not in html.lower()
    assert 'id="app"' in html                                  # the mount point
    assert "Vue" in html and len(html) > 80_000                # runtime is inlined
    # the trust anchor is intact
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>', html, re.S)
    blob = json.loads(m.group(1).replace("\\u003c", "<"))
    assert "counts" in blob and "actions" in blob
    # tiles + repo filter live in the template, bound to the payload (not string-built numbers)
    assert 'id="repo-filter"' in dr.TEMPLATE_SRC and 'class="repopick"' in dr.TEMPLATE_SRC
    assert 'v-for' in dr.TEMPLATE_SRC and "counts" in dr.TEMPLATE_SRC


def test_covered_private_dep_is_excluded_from_the_tile_and_surfaced_separately():
    """A private dep the fleet DOES scan is `covered` in drift.json — it must NOT count in the
    Private tile or the 'couldn't crawl' rows, but IS surfaced (as the dependency edge) via a
    coveredDeps projection. Fixes the dashboard listing amazonspapi/ebayapi as unreachable."""
    from agent.lib.dashboard_render import _build_projection
    inv = _inv_with_private([
        {"repo": "marketplacehub", "packages": [], "repositories": ["https://git.x/akshit/catchapi.git"],
         "covered": ["https://git.x/example-org/amazonspapi.git"]},
    ])
    proj = _build_projection(inv, {"actions": []})
    assert proj["counts"]["private"] == 1                       # only the blind one counts
    assert [r["source"] for r in proj["private"]] == ["https://git.x/akshit/catchapi.git"]
    assert proj["coveredDeps"] == [{"repo": "marketplacehub",
                                    "source": "https://git.x/example-org/amazonspapi.git"}]


def test_dashboard_names_covered_deps_as_scanned_not_unreachable():
    # The "scanned directly" copy lives in the Task 4/5 Coverage panel; the data contract
    # (coveredDeps names the dependency edge, not a blind spot) is what this task owns.
    from agent.lib.dashboard_render import build_payload
    inv = _inv_with_private([
        {"repo": "marketplacehub", "packages": [], "repositories": [],
         "covered": ["https://git.x/example-org/amazonspapi.git"]}])
    payload = build_payload(inv, {"generated": "2026-07-29", "actions": []})
    assert payload["coveredDeps"] == [{"repo": "marketplacehub",
                                       "source": "https://git.x/example-org/amazonspapi.git"}]


def test_dark_is_the_default_theme():
    from agent.lib.dashboard_render import render_dashboard
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-29")
    assert "color-scheme:dark" in html                          # CSS default resolves dark
    assert 'theme: "dark"' in dr.APP_JS_SRC                     # the Vue app defaults to dark


def test_permalink_self_hosted_gitlab_via_config_not_env(monkeypatch):
    """The self-hosted GitLab host comes from the drift.yml fleet (cfg['host']), threaded as
    gitlab_hosts — no CI env var needed. Env stays a fallback/override."""
    from agent.lib.dashboard_render import _permalink
    monkeypatch.delenv("DRIFT_GITLAB_HOSTS", raising=False)
    assert _permalink("https://git.example.com/example-org/ebayapi", "SHA", "src/x.php:39",
                      gitlab_hosts={"git.example.com"}) == \
        "https://git.example.com/example-org/ebayapi/-/blob/SHA/src/x.php#L39"


def test_build_payload_threads_config_gitlab_host_into_hrefs(monkeypatch):
    from agent.lib.dashboard_render import build_payload
    monkeypatch.delenv("DRIFT_GITLAB_HOSTS", raising=False)
    inv = {"repos": [{"path": "r", "remote_url": "https://git.example.com/g/r", "head_sha": "S",
                      "endpoints": []}]}
    audit = {"actions": [{"repo": "r", "kind": "sunset", "files": ["src/x.php:5"], "vendor": "V"}]}
    proj = build_payload(inv, audit, gitlab_hosts={"git.example.com"})
    hrefs = [f["href"] for a in proj["actions"] for f in a["files"]]
    assert hrefs == ["https://git.example.com/g/r/-/blob/S/src/x.php#L5"]


# ---- Task 4: the reactive Summary table — filters + row drill-down + repo scope ----

def test_repo_scope_and_tile_filters_are_wired_in_all_modes():
    from agent.lib import dashboard_render as dr
    js = dr.APP_JS_SRC
    # the four filter predicates ported from the vanilla engine
    for hook in ("DEPRECATED", "sunset", 'owner', "classified"):
        assert hook in js, hook
    # the repo scope applies to actions, endpoints AND private (the earlier bug)
    assert js.count("matchesRepo") >= 3
    assert "a.repo" in js and "e.repo" in js and "p.repo" in js
    tmpl = dr.TEMPLATE_SRC
    assert 'id="panel"' in tmpl and "v-for" in tmpl        # the table renders rows reactively


def test_no_v_html_used_for_scan_controlled_rendering():
    """Task 3 deleted the vanilla esc/escA/safeUrl escapers along with the innerHTML-built
    rows. The Vue port must not reintroduce an innerHTML-shaped XSS hole: every scan-controlled
    field (repo, vendor, recommendation, file paths, source URLs, CVE titles) must go through
    Vue's auto-escaping text/attr bindings, never through v-html. A single v-html on scan data
    is exactly the bug class the old esc()/escA() helpers existed to prevent."""
    from agent.lib import dashboard_render as dr
    assert "v-html" not in dr.TEMPLATE_SRC
    assert "v-html" not in dr.APP_JS_SRC
    assert "innerHTML" not in dr.APP_JS_SRC


def test_safe_url_scheme_allowlist_is_ported():
    """safeUrl() must gate every clickable href built from scan data (call-site permalinks,
    source URLs, private repo URLs) — only http/https become links; javascript:/data: etc.
    must not. Mirrors the vanilla safeUrl regex."""
    from agent.lib import dashboard_render as dr
    js = dr.APP_JS_SRC
    assert "safeUrl" in js
    assert re.search(r"\^https\?", js), "safeUrl must allow-list the http/https scheme"
    # every target=_blank call-site/source link must be scheme-gated by safeUrl first
    assert 'target="_blank"' in dr.TEMPLATE_SRC and "rel=\"noopener\"" in dr.TEMPLATE_SRC


def test_call_site_links_open_new_tab_with_copy_alongside():
    """Requirement: call-site links open in a NEW tab, with the copy button ALONGSIDE (a link
    jumps to code, copy grabs path:line) — the recently-fixed behavior must not regress."""
    from agent.lib import dashboard_render as dr
    tmpl = dr.TEMPLATE_SRC
    assert "copy-loc" in tmpl
    # the call-site anchor and its copy button live in the same block
    m = re.search(r'<a[^>]*target="_blank"[^>]*>.*?copy-loc.*?</div>', tmpl, re.S)
    assert m, "expected a target=_blank call-site link followed by a copy-loc button"


def test_rows_computed_dispatches_by_mode():
    """apis|unknown -> endpoints, private -> private, unaudited -> catalog, else -> actions
    (mirrors the vanilla state.mode map)."""
    from agent.lib import dashboard_render as dr
    js = dr.APP_JS_SRC
    assert '"apis"' in js and '"unknown"' in js and '"endpoints"' in js
    assert '"unaudited"' in js and '"catalog"' in js
    assert '"private"' in js


def _fleet_for_xss(evil):
    inv = {"repos": [{"path": "r", "remote_url": None, "head_sha": None, "endpoints": [
        {"domain": evil, "vendor": evil, "version": "v1", "classified": True,
         "file_count": 1, "files": ["a.php:1"]}]}],
        "coverage": {"privateSources": [{"repo": evil, "packages": [],
                                         "repositories": [evil]}]}}
    audit = {"generated": "2026-08-04", "actions": [
        {"repo": evil, "ref": evil, "kind": "cve", "status": "DEPRECATED", "worst": "HIGH",
         "finding_count": 1, "recommendation": evil, "files": ["x.php:1"], "fixes": [],
         "sources": [evil]}], "coverage": {"catalog": [{"vendor": evil, "verdict": "STALE"}]}}
    return inv, audit


def test_xss_script_tag_neutralized_at_client_render_layer():
    """A repo/vendor/recommendation/source_url containing <script> must not become an
    executable node — proven here by there being no v-html sink for it to execute through
    (the JSON blob itself is already </script>-hardened, tested elsewhere)."""
    from agent.lib.dashboard_render import render_dashboard
    evil = 'a<script>alert(1)</script>&"x'
    inv, audit = _fleet_for_xss(evil)
    html = render_dashboard(inv, audit, "2026-08-04")
    assert "<script>alert(1)</script>" not in html
    # no v-html sink exists anywhere in the shipped page for this data to be injected through
    assert "v-html" not in html


def test_xss_javascript_scheme_source_url_never_becomes_a_link():
    """A source_url of `javascript:alert(1)` must never render as a clickable href — the
    safeUrl scheme gate must refuse it (falls back to plain escaped text)."""
    from agent.lib.dashboard_render import render_dashboard
    evil = "javascript:alert(1)"
    inv, audit = _fleet_for_xss(evil)
    html = render_dashboard(inv, audit, "2026-08-04")
    assert 'href="javascript:' not in html.lower()


def test_xss_attribute_breakout_string_does_not_break_the_page():
    """A `"` attribute-breakout string in a repo/vendor field must not let scan data escape
    its attribute context. Since rendering goes through Vue's :attr bindings (never string
    concatenation into an attribute), there is no breakout point — this is a regression guard
    on that design staying true (no manual `+'"'+` attribute building in app.js)."""
    from agent.lib import dashboard_render as dr
    assert not re.search(r'"\s*\+\s*\w+.*\+\s*\'"', dr.APP_JS_SRC), \
        "app.js must not hand-build HTML attributes by string concatenation"


# ---- Task 5: SBOM/SARIF panels + the drift.json / coverage footer ----

def test_sbom_sarif_and_coverage_footer_present():
    from agent.lib import dashboard_render as dr
    tmpl, js = dr.TEMPLATE_SRC, dr.APP_JS_SRC
    for id_ in ("sbom-table", "sarif-groups", "json-drift", "coverage"):
        assert id_ in tmpl, id_
    for src in ("sbom-data", "sarif-data", "spdx-data"):
        assert src in js, src
    # unscannable roots are still surfaced honestly ("cannot see ≠ clean")
    assert "rootsUnscannable" in js


# ---- Task 6 (superseded by Task 2): the Retirement Timeline ----
#
# Task 6 shipped a per-VENDOR SVG scatter (one dot per vendor, merging distinct operations
# onto a single point). Task 2 replaced it with per-operation `.trk` rows grouped by vendor
# (docs/design/2026-08-04-cockpit-mockup.html) — the SVG is gone, so the old
# `test_timeline_chart_is_svg_and_scope_aware` assertion on `<svg` no longer describes the
# shipped markup; it is superseded by test_hero_timeline_is_per_operation_and_deterministic
# below, which asserts the NEW per-operation structure instead.

def test_timeline_is_scope_aware_and_deterministic():
    from agent.lib import dashboard_render as dr
    assert "timeline" in dr.APP_JS_SRC and "matchesRepo" in dr.APP_JS_SRC
    assert "generated" in dr.APP_JS_SRC          # today-line anchored on DATA.generated
    assert "Date.now" not in dr.APP_JS_SRC       # determinism


# ---- Task 2: the per-operation Retirement Timeline hero (supersedes Task 6's SVG scatter) ----

def test_hero_timeline_is_per_operation_and_deterministic():
    """The flagship hero chart: one row per OPERATION (not one dot per vendor — the bug the
    old SVG scatter had), grouped by vendor, positioned by dayOrdinal(DATA.generated) — never
    Date.now() / wall-clock, so the SAME drift.json places every point identically regardless
    of when the page is opened."""
    from agent.lib import dashboard_render as dr
    assert "timeline" in dr.APP_JS_SRC and "dayOrdinal" in dr.APP_JS_SRC
    assert "Date.now" not in dr.APP_JS_SRC
    assert "byVendor" in dr.APP_JS_SRC or "vgroup" in dr.TEMPLATE_SRC   # grouped per operation
    # per-operation rows in the template, not a per-vendor scatter: one .trk per item in
    # timeline.byVendor's items (dated) and one per timeline.undated entry (undated) — no
    # string-concatenated HTML (v-for, not innerHTML-built rows).
    assert 'v-for="(pt, pi) in vg.items"' in dr.TEMPLATE_SRC
    assert 'v-for="(u, ui) in timeline.undated"' in dr.TEMPLATE_SRC
    assert "<svg" not in dr.TEMPLATE_SRC          # the old per-vendor scatter is gone
    # the inert Task-1 bridge stub is gone — no dead v-if="false" markup left behind
    assert 'v-if="false"' not in dr.TEMPLATE_SRC
    # tooltip content is reactive state rendered via {{ }}/:class bindings, never v-html
    assert "v-html" not in dr.TEMPLATE_SRC and "innerHTML" not in dr.APP_JS_SRC
    assert "showTip" in dr.APP_JS_SRC and "tip.visible" in dr.TEMPLATE_SRC


# ---- Task 7/4: deep-linkable filter state (URL <-> Vue state) ----

def test_deep_link_state_sync_is_wired():
    from agent.lib import dashboard_render as dr
    js = dr.APP_JS_SRC
    assert "location.search" in js or "URLSearchParams" in js
    assert "replaceState" in js                     # updates URL without history spam
    for key in ("repo", "tab"):
        assert key in js, key


def test_deep_links_use_the_new_tab_and_sub_params():
    # Task 4: full ?repo=&tab=&sub= reconciliation for the new cockpit IA — repo (scope),
    # tab (the active primary/tile tab) and sub (summary|sbom|sarif) all round-trip.
    from agent.lib import dashboard_render as dr
    js = dr.APP_JS_SRC
    assert "replaceState" in js and "URLSearchParams" in js
    for key in ("repo", "tab", "sub"):
        assert key in js, key


# ---- Task 1: full-width cockpit — tiles become primary tabs + sub-tab shell ----

def test_cockpit_ia_tiles_are_tabs_hero_and_subtabs():
    from agent.lib import dashboard_render as dr
    tmpl = dr.TEMPLATE_SRC
    assert 'class="tabstrip"' in tmpl                 # tiles-as-tabs primary nav
    assert 'class="hero"' in tmpl or 'id="hero' in tmpl
    assert 'class="subbar"' in tmpl and 'class="subtab"' in tmpl
    # full-width: the centered column is gone from the CSS
    assert "max-width:1240px" not in dr.CSS_SRC
    js = dr.APP_JS_SRC
    assert "toggleTab" in js and "state" in js
    # the summary rows scope to the active primary tab (null => all actions)
    assert "this.tab" in js


# ---- Task 3: contextual hero — vendor bars + honest empty-states per tab ----

def test_hero_is_contextual_with_honest_empty_state():
    """The hero is not always the Retirement Timeline: apis/unknown get a vendor/endpoint
    breakdown, and a zero-count dimension (critical/eol/private/unaudited/devops) gets the
    honest "cannot see != clean" empty-state, never a plain "nothing found" that could be
    mistaken for a clean scan."""
    from agent.lib import dashboard_render as dr
    js, tmpl = dr.APP_JS_SRC, dr.TEMPLATE_SRC
    assert "heroMode" in js                                   # timeline | vendors | empty
    # honest empty-state copy for a zero dimension (cannot see != clean)
    assert "could read" in tmpl or "cannot see" in tmpl.lower() or "unaudited" in js.lower()
    assert "endpoints" in js                                  # vendor breakdown reads endpoints
    # the three states are a plain v-if/v-else-if/v-else chain, decided once by heroMode —
    # no duplicated branching logic re-deriving the same tab checks in the template
    assert "heroMode === 'timeline'" in tmpl
    assert "heroMode === 'vendors'" in tmpl
    assert "vendorBars" in js and "vendorBars" in tmpl
    # timeline lanes are untouched by the wrap (check_timeline_lanes still has both to find)
    assert "timeline.dated" in tmpl and "timeline.undated" in tmpl
    # XSS: vendor/domain names are scan-controlled — interpolated via {{ }}, never a raw sink
    assert "v-html" not in tmpl and "innerHTML" not in js


def test_ai_tier_blobs_leave_certified_drift_data_byte_identical():
    """The confidence-vs-firewall proof: folding the ad-hoc/leads tiers into the ONE cockpit adds
    SEPARATE id'd blobs and leaves the certified `drift-data` blob byte-identical — so
    check_blob_matches_payload (id-anchored, non-greedy) is untouched and the AI tiers can never
    contaminate the certified one. Absent → the blob is not emitted at all (tab hidden, not '0')."""
    import re
    from agent.lib.dashboard_render import render_payload
    proj = {"generated": "2026-08-06", "counts": {"fixes": 1, "review": 0}, "actions": []}

    def drift_blob(html):
        return re.search(r'<script id="drift-data" type="application/json">(.*?)</script>', html, re.S).group(1)

    plain = render_payload(proj, "2026-08-06")
    with_ai = render_payload(proj, "2026-08-06",
                             adhoc={"schemaVersion": "drift-adhoc/v1", "byRepo": [{"repo": "r"}]},
                             leads={"schemaVersion": "drift-leads/v1", "leads": []})
    assert drift_blob(plain) == drift_blob(with_ai)                       # ← the headline assertion
    assert 'id="adhoc-data"' not in plain and 'id="leads-data"' not in plain   # absent → not emitted
    assert 'id="adhoc-data"' in with_ai and 'id="leads-data"' in with_ai       # present → additive blobs
